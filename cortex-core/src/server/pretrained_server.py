"""
Lightweight OpenAI-compatible server for pretrained HuggingFace models.
Usage: python3 pretrained_server.py --model TinyLlama/TinyLlama-1.1B-Chat-v1.0 --port 8081
"""
import json
import os
import time
import asyncio
import logging
import torch
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel, Field
from pathlib import Path

logger = logging.getLogger("pretrained")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")

app = FastAPI(title="Pretrained Model API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type"],
)

model_pipeline = None
model_name = ""
device = "cpu"

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatCompletionRequest(BaseModel):
    model: str = Field(default="pretrained")
    messages: list[ChatMessage]
    max_tokens: int = Field(default=256, ge=1, le=4096)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    top_p: float = Field(default=1.0, ge=0.0, le=1.0)
    stream: bool = Field(default=False)
    stop: list[str] | None = None
    user_id: str | None = None

class ModelInfo(BaseModel):
    id: str
    object: str = "model"
    created: int
    owned_by: str = "pretrained"

class ModelList(BaseModel):
    object: str = "list"
    data: list[ModelInfo]


def load_model(m: str):
    global model_pipeline, model_name, device
    model_name = m

    from transformers import AutoModelForCausalLM, AutoTokenizer

    logger.info(f"Downloading/loading {m}...")
    tok = AutoTokenizer.from_pretrained(m, trust_remote_code=True)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        m,
        torch_dtype=torch.float16 if device == "cuda" else torch.float32,
        device_map="auto" if device == "cuda" else None,
        trust_remote_code=True,
        low_cpu_mem_usage=True,
    )
    model.eval()
    if device == "cpu":
        model = model.to("cpu")

    model_pipeline = {"model": model, "tokenizer": tok}
    params = sum(p.numel() for p in model.parameters())
    logger.info(f"Loaded: {m} ({params:,} params)")


def format_prompt(messages: list[ChatMessage]) -> str:
    parts = []
    for msg in messages:
        if msg.role == "system":
            parts.append(f"System: {msg.content}")
        elif msg.role == "user":
            parts.append(f"User: {msg.content}")
        elif msg.role == "assistant":
            parts.append(f"Assistant: {msg.content}")
    parts.append("Assistant:")
    return "\n".join(parts)


@app.get("/health")
async def health():
    return {"status": "ok", "model": model_name, "loaded": model_pipeline is not None}

@app.get("/v1/models")
async def list_models():
    return ModelList(data=[ModelInfo(id=model_name, created=int(time.time()))])


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatCompletionRequest):
    global model_pipeline
    if model_pipeline is None:
        raise HTTPException(503, "Model not loaded")

    prompt = format_prompt(req.messages)
    tok = model_pipeline["tokenizer"]
    model = model_pipeline["model"]

    inputs = tok(prompt, return_tensors="pt").to(device)

    if req.stream:
        return EventSourceResponse(stream_generate(inputs, req, tok, model))

    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=req.max_tokens,
            temperature=req.temperature,
            top_p=req.top_p,
            do_sample=True,
            pad_token_id=tok.pad_token_id,
            eos_token_id=tok.eos_token_id,
        )

    generated_ids = outputs[0][inputs.input_ids.shape[1]:]
    text = tok.decode(generated_ids, skip_special_tokens=True)

    return {
        "id": f"chatcmpl-{int(time.time())}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": req.model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
        "usage": {
            "prompt_tokens": inputs.input_ids.shape[1],
            "completion_tokens": len(generated_ids),
            "total_tokens": inputs.input_ids.shape[1] + len(generated_ids),
        },
    }


async def stream_generate(inputs, req, tok, model):
    yield json.dumps({"choices": [{"delta": {"role": "assistant"}, "index": 0}]})

    prompt_len = inputs.input_ids.shape[1]
    x = inputs.input_ids
    past = None

    for i in range(req.max_tokens):
        with torch.no_grad():
            if past is None:
                out = model(**inputs, use_cache=True)
            else:
                out = model(input_ids=x[:, -1:], past_key_values=past, use_cache=True)

        logits = out.logits[:, -1, :] / req.temperature
        probs = torch.softmax(logits, dim=-1)

        if req.top_p < 1.0:
            sorted_probs, sorted_indices = torch.sort(probs, descending=True)
            cumsum = torch.cumsum(sorted_probs, dim=-1)
            remove = cumsum > req.top_p
            remove[:, 1:] = remove[:, :-1].clone()
            remove[:, 0] = False
            probs[0, sorted_indices[0][remove[0]]] = 0

        next_token = torch.multinomial(probs, num_samples=1)
        token_text = tok.decode(next_token[0], skip_special_tokens=True)

        yield json.dumps({"choices": [{"delta": {"content": token_text}, "index": 0}]})

        x = torch.cat([x, next_token], dim=-1)
        past = out.past_key_values

        if next_token.item() == tok.eos_token_id:
            break

        await asyncio.sleep(0)

    yield json.dumps({"choices": [{"delta": {}, "finish_reason": "stop", "index": 0}]})
    yield "data: [DONE]"


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=str, default="TinyLlama/TinyLlama-1.1B-Chat-v1.0")
    parser.add_argument("--port", type=int, default=8081)
    parser.add_argument("--host", type=str, default="127.0.0.1")
    args = parser.parse_args()

    load_model(args.model)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
