"""
OpenAI-compatible server for HuggingFace models with per-user memory.
Default model: GPT-2 (fast on CPU, ~3.5 tok/s on Intel Mac).
Usage: python3 pretrained_server.py --model gpt2 --port 8081
"""
import json
import os
import sys
import time
import asyncio
import logging
from typing import Optional, List
import torch
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel, Field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from user_store import UserStore

logger = logging.getLogger("aura")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")

app = FastAPI(title="Aura API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type"],
)

model_pipeline = None
model_name = ""
device = "cpu"
user_store = None
MAX_HISTORY_CONVOS = 5

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatCompletionRequest(BaseModel):
    model: str = Field(default="gpt2")
    messages: list[ChatMessage]
    max_tokens: int = Field(default=256, ge=1, le=4096)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    top_p: float = Field(default=1.0, ge=0.0, le=1.0)
    top_k: int = Field(default=50, ge=0, le=500)
    repetition_penalty: float = Field(default=1.1, ge=1.0, le=2.0)
    stream: bool = Field(default=False)
    stop: Optional[List[str]] = None
    user_id: Optional[str] = None

class ModelInfo(BaseModel):
    id: str
    object: str = "model"
    created: int
    owned_by: str = "aura"

class ModelList(BaseModel):
    object: str = "list"
    data: list[ModelInfo]


def load_model(m: str):
    global model_pipeline, model_name, device
    model_name = m

    from transformers import AutoModelForCausalLM, AutoTokenizer

    logger.info(f"Loading {m}...")
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


def format_prompt(messages: List[ChatMessage], user_id: Optional[str] = None) -> str:
    parts = ["The following is a conversation between a user and an AI assistant."]
    if user_id and user_store:
        history = user_store.get_recent_conversations(user_id, n=MAX_HISTORY_CONVOS)
        if history:
            for c in history:
                parts.append(f"User: {c['prompt']}")
                parts.append(f"Assistant: {c['completion']}")
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

@app.get("/v1/users")
async def list_users():
    if user_store is None:
        return {"users": []}
    return {"users": user_store.list_users()}

@app.delete("/v1/users/{user_id}")
async def delete_user(user_id: str):
    if user_store is None:
        raise HTTPException(503, "User store not available")
    user_store.clear_user(user_id)
    return {"status": "deleted", "user_id": user_id}


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatCompletionRequest):
    global model_pipeline
    if model_pipeline is None:
        raise HTTPException(503, "Model not loaded")

    prompt = format_prompt(req.messages, req.user_id)
    tok = model_pipeline["tokenizer"]
    model = model_pipeline["model"]

    inputs = tok(prompt, return_tensors="pt").to(device)

    if req.stream:
        return EventSourceResponse(stream_generate(inputs, req, tok, model, prompt))

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

    _save_conversation(req, prompt, text)

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


async def stream_generate(inputs, req, tok, model, prompt: str):
    yield json.dumps({"choices": [{"delta": {"role": "assistant"}, "index": 0}]})

    prompt_len = inputs.input_ids.shape[1]
    x = inputs.input_ids
    past = None
    full_text = ""

    for i in range(req.max_tokens):
        with torch.no_grad():
            if past is None:
                out = model(**inputs, use_cache=True)
            else:
                out = model(input_ids=x[:, -1:], past_key_values=past, use_cache=True)

        logits = out.logits[:, -1, :] / req.temperature

        if req.repetition_penalty != 1.0:
            for token_id in x[0].tolist():
                logits[:, token_id] /= req.repetition_penalty

        if req.top_k > 0:
            values, _ = torch.topk(logits, req.top_k, dim=-1)
            logits[logits < values[:, -1:]] = float("-inf")

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
        full_text += token_text

        yield json.dumps({"choices": [{"delta": {"content": token_text}, "index": 0}]})

        x = torch.cat([x, next_token], dim=-1)
        past = out.past_key_values

        if next_token.item() == tok.eos_token_id:
            break

        await asyncio.sleep(0)

    _save_conversation(req, prompt, full_text)
    yield json.dumps({"choices": [{"delta": {}, "finish_reason": "stop", "index": 0}]})
    yield "data: [DONE]"


def _save_conversation(req: ChatCompletionRequest, prompt: str, response: str):
    if user_store is None or not req.user_id:
        return
    try:
        user_prompt = req.messages[-1].content if req.messages else ""
        user_store.add_conversation(req.user_id, user_prompt, response)
    except Exception as e:
        logger.warning(f"Failed to save conversation: {e}")


if __name__ == "__main__":
    import sys
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=str, default="gpt2")
    parser.add_argument("--port", type=int, default=8081)
    parser.add_argument("--host", type=str, default="127.0.0.1")
    parser.add_argument("--user-dir", type=str, default=None)
    args = parser.parse_args()

    user_dir = args.user_dir or str(Path(__file__).resolve().parent.parent.parent / "users")
    user_store = UserStore(user_dir)
    logger.info(f"User store: {user_dir}")

    load_model(args.model)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
