"""
OpenAI-compatible HTTP server for the Cortex model.
- POST /v1/chat/completions — chat completions (streaming + non-streaming)
- GET  /v1/models — list available models
- GET  /health — health check
"""
from __future__ import annotations
import json
import os
import re
import time
import asyncio
import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from collections import OrderedDict
from typing import AsyncGenerator, Optional

logger = logging.getLogger("cortex")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")

import torch
import torch.nn.functional as F
import uvicorn
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel, Field

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "cortex-train"))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "cortex-rag"))
from model import UniversalDenseCore
from hypernetwork import HyperNetwork, apply_lora_to_model, clear_lora_from_model
from improvement import SelfImprovementEngine
from user_store import UserStore
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "cortex-core" / "src"))
from agent.agent import Agent
from agent.identity import Identity

@asynccontextmanager
async def lifespan(app: FastAPI):
    global improvement_engine, agent, knowledge_base, user_store

    ckpt = os.environ.get("CORTEX_CHECKPOINT")
    data_dir = os.environ.get("CORTEX_DATA_DIR", str(Path(__file__).resolve().parents[3] / "cortex-train" / "data"))
    user_dir = os.environ.get("CORTEX_USER_DIR", str(Path(__file__).resolve().parents[3] / "cortex-core" / "users"))
    user_store = UserStore(user_dir)
    quantize = os.environ.get("CORTEX_QUANTIZE", "none")
    load_model(ckpt, data_dir, quantize)
    hypernet_ckpt = os.environ.get("CORTEX_HYPERNET_CHECKPOINT")
    load_hypernetwork(hypernet_ckpt)

    param_count = sum(p.numel() for p in model.parameters()) if model else 0
    logger.info(f"Model ready: {param_count:,} params on {device}")
    if hypernetwork:
        hn_count = sum(p.numel() for p in hypernetwork.parameters())
        logger.info(f"Hypernetwork ready: {hn_count:,} params")

    prompt_dir = os.environ.get("CORTEX_PROMPT_DIR", "")
    if prompt_dir and Path(prompt_dir).exists() and model is not None:
        from ingestion import build_knowledge_base
        kb_path = f"/tmp/cortex_kb_{int(time.time())}.npz"
        knowledge_base = build_knowledge_base(
            prompt_dir, model, tokenizer, device, output_path=kb_path,
        )
        os.environ["CORTEX_KNOWLEDGE_BASE"] = kb_path
        logger.info(f"[kb] built from {prompt_dir}: {len(knowledge_base['texts'])} chunks")

    if hypernetwork is not None and model is not None and improvement_engine is None:
        imp_dir = os.environ.get("CORTEX_IMPROVEMENT_DIR", "")
        if imp_dir:
            os.makedirs(imp_dir, exist_ok=True)
        improvement_engine = SelfImprovementEngine(
            hypernetwork=hypernetwork,
            base_model=model,
            lora_rank=hypernetwork_config.get("lora_rank", 8),
            device=device,
            checkpoint_dir=imp_dir or None,
        )
        logger.info(f"[improvement] engine ready, checkpoint_dir={imp_dir or '(none)'}")

    if hypernetwork is not None and model is not None and agent is None:
        kb_path = os.environ.get("CORTEX_KNOWLEDGE_BASE", "")
        if kb_path and Path(kb_path).exists():
            from ingestion import load_knowledge_base
            knowledge_base = load_knowledge_base(kb_path)
            logger.info(f"[agent] loaded knowledge base: {len(knowledge_base['texts'])} chunks")

        identity_path = os.environ.get("CORTEX_IDENTITY_PATH", "")
        agent = Agent(
            base_model=model,
            hypernetwork=hypernetwork,
            lora_rank=hypernetwork_config.get("lora_rank", 8),
            d_model=model.d_model,
            device=device,
            knowledge_base=knowledge_base,
            identity_path=identity_path or None,
            memory_path=os.environ.get("CORTEX_MEMORY_PATH", "memory.sqlite"),
        )
        logger.info(f"[agent] ready, identity v{agent.identity.version}")

    yield

    # Shutdown: save identity and close memory
    if agent is not None:
        identity_path = os.environ.get("CORTEX_IDENTITY_PATH", "")
        if identity_path:
            agent.save_identity(identity_path)
            logger.info(f"[shutdown] identity saved to {identity_path}")
        try:
            agent.fact_memory.close()
        except Exception:
            pass


app = FastAPI(title="Cortex API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",       # Vite dev server
        "https://tauri.localhost",     # Tauri v2 production webview
        "tauri://localhost",           # Tauri v2 fallback origin
    ],
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type"],
)

# --- Model globals ---
model: UniversalDenseCore | None = None
hypernetwork: HyperNetwork | None = None
hypernetwork_config: dict = {}
tokenizer = None
model_config: dict = {}
device = "cpu"

# Per-user personalization
user_store: UserStore | None = None

# LoRA cache: task_string -> list[(A, B)]  (on CPU)
lora_cache: OrderedDict[str, list[tuple[torch.Tensor, torch.Tensor]]] = OrderedDict()
LORA_CACHE_MAX = 32
lora_cache_hits = 0
lora_cache_misses = 0

# Self-improvement engine (online hypernetwork fine-tuning)
improvement_engine: SelfImprovementEngine | None = None
_request_counter = 0
_improvement_interval = 5  # collect N examples before triggering a step
_model_lock = threading.Lock()

# Per-user direct LoRA training (bypasses HyperNetwork bottleneck)
_user_lora_steps_since_train: dict[str, int] = {}

# Agent (identity, memory, knowledge base, tools)
agent: Agent | None = None
knowledge_base: dict | None = None


# --- Pydantic schemas ---

class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str = Field(default="cortex-core", description="Model ID")
    messages: list[ChatMessage]
    max_tokens: int = Field(default=256, ge=1, le=4096)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    top_p: float = Field(default=1.0, ge=0.0, le=1.0)
    stream: bool = Field(default=False)
    stop: Optional[list[str]] = None
    task: Optional[str] = Field(default=None, description="Task description for on-demand LoRA generation")
    user_id: Optional[str] = Field(default=None, description="User ID for per-user LoRA personalization")


class ModelInfo(BaseModel):
    id: str
    object: str = "model"
    created: int
    owned_by: str = "cortex"


class ModelList(BaseModel):
    object: str = "list"
    data: list[ModelInfo]


class ToolExecuteRequest(BaseModel):
    tool_name: str
    tool_args: list[str] = []
    context_text: str = ""
    max_tokens: int = Field(default=128, ge=16, le=2048)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    top_p: float = Field(default=1.0, ge=0.0, le=1.0)


# --- Helpers ---

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


def load_model(ckpt_path: str | None, data_dir: str, quantize_mode: str = "none"):
    global model, tokenizer, model_config, device

    if not ckpt_path or not Path(ckpt_path).exists():
        logger.warning(f"No checkpoint at {ckpt_path}, using random init")
        model_config = {"vocab_size": 16384, "d_model": 768, "n_layers": 6,
                        "n_heads": 12, "d_ff": 2048, "max_steps": 4}
        model = UniversalDenseCore(**model_config).to(device)
        model.eval()
    else:
        logger.info(f"Loading model from {ckpt_path}")
        ckpt = torch.load(ckpt_path, map_location=device)
        model_config = ckpt.get("config", {})
        model = UniversalDenseCore(**model_config)
        model.load_state_dict(ckpt["model_state_dict"])
        model.to(device)
        model.eval()

    if quantize_mode != "none":
        mode_name = {"fp16": "float16", "int8": "int8"}.get(quantize_mode, quantize_mode)
        logger.info(f"Quantizing model to {mode_name}...")
        model.quantize(quantize_mode)

    global tokenizer
    tok_type = ckpt.get("tokenizer", "") if ckpt_path and Path(ckpt_path).exists() else ""
    if tok_type == "gpt2":
        from tokenizers import Tokenizer as HFTokenizer
        tokenizer = HFTokenizer.from_pretrained("gpt2")
        logger.info(f"  using GPT-2 tokenizer (vocab={tokenizer.get_vocab_size()})")
    else:
        tok_path = Path(data_dir) / "tokenizer.json"
        if not tok_path.exists():
            raise RuntimeError(
                f"Tokenizer not found at {tok_path}. "
                "Run `python prepare_data.py` to train a tokenizer, "
                "or set CORTEX_DATA_DIR to a directory containing tokenizer.json"
            )
        from tokenizers import Tokenizer as HFTokenizer
        tokenizer = HFTokenizer.from_file(str(tok_path))
        tok_vocab = tokenizer.get_vocab_size()
        model_vocab = model.output.weight.shape[0]
        if tok_vocab != model_vocab:
            raise RuntimeError(
                f"Tokenizer vocab size ({tok_vocab}) does not match "
                f"model vocab size ({model_vocab}). "
                "Use a tokenizer that matches the model's training configuration."
            )
        logger.info(f"  tokenizer vocab={tok_vocab} matches model ✓")
    model.tokenizer = tokenizer

    logger.info(f"  {sum(p.numel() for p in model.parameters()):,} params loaded")


def load_hypernetwork(ckpt_path: str | None):
    global hypernetwork, hypernetwork_config
    if not ckpt_path or not Path(ckpt_path).exists():
        logger.warning("No hypernetwork checkpoint provided; task-based LoRA disabled")
        hypernetwork = None
        return
    logger.info(f"Loading hypernetwork from {ckpt_path}")
    ckpt = torch.load(ckpt_path, map_location=device)
    cfg = ckpt.get("config", {"d_model": 768, "lora_rank": 8, "n_layers": 6})
    hypernetwork_config = cfg
    from hypernetwork import HyperNetwork
    hypernetwork = HyperNetwork(**cfg).to(device)
    hypernetwork.load_state_dict(ckpt["hypernet_state_dict"])
    hypernetwork.eval()
    logger.info(f"  {sum(p.numel() for p in hypernetwork.parameters()):,} params loaded")


def apply_task_lora(task: str) -> torch.Tensor | None:
    """Generate LoRA from a task description and apply it to the base model.
    Caches LoRA weights by task string (LRU, up to LORA_CACHE_MAX entries).
    Returns task_embedding for the improvement engine."""
    global model, hypernetwork, tokenizer, lora_cache, lora_cache_hits, lora_cache_misses

    if hypernetwork is None:
        return None

    ids = encode(task)
    with torch.no_grad():
        emb = model.embedding(ids) * (model.d_model ** 0.5)
        task_emb = emb.mean(dim=1)

    if task in lora_cache:
        lora_cache.move_to_end(task)
        lora_cache_hits += 1
        loras = lora_cache[task]
    else:
        with torch.no_grad():
            generated = hypernetwork(task_emb)

        loras = [(A.cpu(), B.cpu()) for A, B in generated]
        lora_cache[task] = loras
        lora_cache_misses += 1

        if len(lora_cache) > LORA_CACHE_MAX:
            lora_cache.popitem(last=False)

    loras_device = [(A.to(device), B.to(device)) for A, B in loras]
    apply_lora_to_model(model, loras_device, rank=hypernetwork_config.get("lora_rank", 8))
    return task_emb


def apply_user_lora(user_id: str) -> torch.Tensor | None:
    """Apply per-user LoRA from saved weights or generate on-demand from history."""
    global model, hypernetwork, tokenizer, device, user_store
    if hypernetwork is None or user_store is None:
        return None

    emb = user_store.get_embedding(user_id)
    if emb is None:
        conversations = user_store.get_recent_conversations(user_id)
        emb = UserStore.compute_embedding_from_history(
            conversations, model, tokenizer, device,
        )
        user_store.save_embedding(user_id, emb)

    emb = emb.to(device)

    if user_store.has_lora(user_id):
        loras = user_store.load_lora(user_id, device)
        if loras is not None:
            apply_lora_to_model(model, loras, rank=hypernetwork_config.get("lora_rank", 8))
            return emb

    with torch.no_grad():
        generated = hypernetwork(emb)
    loras = [(A.cpu(), B.cpu()) for A, B in generated]
    user_store.save_lora(user_id, loras)
    loras_device = [(A.to(device), B.to(device)) for A, B in loras]
    apply_lora_to_model(model, loras_device, rank=hypernetwork_config.get("lora_rank", 8))
    return emb


def clear_task_lora():
    """Remove any active LoRA adapters from the model."""
    if model is not None:
        clear_lora_from_model(model)


def _run_user_lora_training(user_id: str):
    """Train LoRA directly on a user's conversation history (unlimited, no HyperNetwork bottleneck)."""
    global model, tokenizer, device, user_store, hypernetwork_config
    if model is None or user_store is None:
        return
    try:
        conversations = user_store.get_recent_conversations(user_id, n=50)
        if len(conversations) < 3:
            return
        rank = hypernetwork_config.get("lora_rank", 8)
        init_loras = user_store.load_lora(user_id, device)
        with _model_lock:
            loras = UserStore.train_lora_on_user_data(
                model, tokenizer, conversations,
                lora_rank=rank, steps=20, device=device,
                init_loras=init_loras,
            )
        user_store.save_lora(user_id, loras)
        logger.info(f"[user] direct LoRA trained for {user_id} ({len(conversations)} conversations)")
    except Exception as e:
        logger.warning(f"[user] LoRA training failed for {user_id}: {e}")


def _run_improvement_step():
    """Run one improvement step in a background thread, then save checkpoint."""
    global improvement_engine
    if improvement_engine is None:
        return
    with _model_lock:
        loss = improvement_engine.step()
    if loss is not None:
        logger.info(f"[improvement] step {improvement_engine.steps} | loss {loss:.4f} | "
              f"buffer {len(improvement_engine.buffer)} | "
              f"total collected {improvement_engine.examples_collected}")
        if improvement_engine.steps % 5 == 0 and improvement_engine.checkpoint_dir:
            path = Path(improvement_engine.checkpoint_dir) / f"improvement_step_{improvement_engine.steps:04d}.pt"
            improvement_engine.save_checkpoint(str(path))
            logger.info(f"[improvement] saved {path}")


def encode(text: str) -> torch.Tensor:
    if tokenizer is None:
        raise RuntimeError("Tokenizer not loaded — cannot encode text")
    ids = tokenizer.encode(text).ids
    return torch.tensor([ids], dtype=torch.long)


def decode(ids: list[int]) -> str:
    if tokenizer is None:
        raise RuntimeError("Tokenizer not loaded — cannot decode text")
    return tokenizer.decode(ids)


# --- Routes ---

@app.get("/health")
async def health():
    mode = "none"
    if model is not None:
        probe = model.blocks[0].attention.wq
        if "quantized" in type(probe).__module__:
            mode = "int8"
        elif probe.weight.dtype == torch.float16:
            mode = "fp16"
        elif probe.weight.dtype == torch.float32:
            mode = "fp32"
    return {
        "status": "ok",
        "model_loaded": model is not None,
        "hypernetwork_loaded": hypernetwork is not None,
        "precision": mode,
    }

@app.get("/v1/tasks/cache")
async def get_task_cache():
    tasks = list(lora_cache.keys())
    return {
        "size": len(tasks),
        "max_size": LORA_CACHE_MAX,
        "hits": lora_cache_hits,
        "misses": lora_cache_misses,
        "tasks": tasks,
    }

@app.delete("/v1/tasks/cache")
async def clear_task_cache():
    lora_cache.clear()
    return {"status": "cleared"}


@app.get("/v1/improvement")
async def improvement_stats():
    if improvement_engine is None:
        return {"status": "disabled"}
    stats = improvement_engine.stats()
    stats["ready"] = improvement_engine.ready
    return {"status": "active", **stats}

@app.get("/v1/knowledge-base")
async def kb_stats():
    if knowledge_base is None:
        return {"status": "disabled"}
    return {
        "status": "active",
        "chunks": len(knowledge_base.get("texts", [])),
        "sources": list(set(knowledge_base.get("sources", []))),
    }


@app.post("/v1/improvement/trigger")
async def trigger_improvement():
    global improvement_engine
    if improvement_engine is None or not improvement_engine.ready:
        return {"status": "skipped", "reason": "not ready or disabled"}
    t = threading.Thread(target=_run_improvement_step, daemon=True)
    t.start()
    return {"status": "started"}


# --- Agent endpoints ---

@app.get("/v1/agent/state")
async def agent_state():
    if agent is None:
        return {"status": "disabled"}
    return {"status": "active", **agent.get_state()}

@app.post("/v1/agent/chat")
async def agent_chat(req: ChatCompletionRequest):
    global agent, improvement_engine, _request_counter
    if agent is None or model is None:
        raise HTTPException(503, "Agent not loaded")

    prompt = format_prompt(req.messages)

    if req.stream:
        return EventSourceResponse(stream_agent_generate(prompt, req))

    with _model_lock:
        text, loss_val, suggestions = agent.generate(
            prompt,
            max_new_tokens=req.max_tokens,
            temperature=req.temperature,
            top_p=req.top_p,
            auto_execute_tools=False,
        )

    # Feed into self-improvement (uses loss computed on LoRA-augmented model)
    if improvement_engine is not None and loss_val is not None:
        task_emb = agent.identity().to(device)
        prompt_ids = encode(prompt)
        completion_ids = encode(text)
        if prompt_ids.shape[1] > 0 and completion_ids.shape[1] > 0:
            improvement_engine.collect(task_emb, prompt_ids, completion_ids, loss_val)
            _request_counter += 1
            if _request_counter % _improvement_interval == 0 and improvement_engine.ready:
                t = threading.Thread(target=_run_improvement_step, daemon=True)
                t.start()

    prompt_toks = tokenizer.encode(prompt).ids if tokenizer else []
    text_toks = tokenizer.encode(text).ids if tokenizer else []

    resp = {
        "id": f"chatcmpl-{int(time.time())}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": "cortex-agent",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": text},
            "finish_reason": "tool_suggestion" if suggestions else "stop",
        }],
        "usage": {
            "prompt_tokens": len(prompt_toks),
            "completion_tokens": len(text_toks),
            "total_tokens": len(prompt_toks) + len(text_toks),
        },
    }
    if suggestions:
        resp["tool_suggestions"] = suggestions
    return resp


@app.post("/v1/agent/tool/execute")
async def agent_tool_execute(req: ToolExecuteRequest):
    """Execute a confirmed tool call and return the continuation."""
    global agent
    if agent is None or model is None:
        raise HTTPException(503, "Agent not loaded")

    with _model_lock:
        result = agent.execute_tool_and_continue(
            req.tool_name, req.tool_args, req.context_text,
            max_new_tokens=req.max_tokens,
            temperature=req.temperature,
            top_p=req.top_p,
        )

    return {
        "tool_name": req.tool_name,
        "result": result,
    }


async def stream_agent_generate(
    prompt: str,
    req: ChatCompletionRequest,
) -> AsyncGenerator[str, None]:
    """Stream agent generation with tool call support."""
    global agent
    yield json.dumps({"choices": [{"delta": {"role": "assistant"}, "index": 0}]})

    with _model_lock:
        task_emb = agent.compose_task_embedding(prompt)
        agent.generate_lora(task_emb)

    if not hasattr(model, 'tokenizer') or model.tokenizer is None:
        raise RuntimeError("Tokenizer not loaded")
    ids = model.tokenizer.encode(prompt).ids
    prompt_tensor = torch.tensor([ids], device=device)

    # Buffer for tool call detection
    all_token_texts = []
    full_raw_text = ""

    # Helper to generate and stream one token
    def generate_stream_token(pt: torch.Tensor, pkv, n: int) -> tuple[torch.Tensor, torch.Tensor, str]:
        with _model_lock:
            if pkv is None:
                logits, _, new_kv = model.forward(pt, use_cache=True)
            else:
                logits, _, new_kv = model.forward(pt, past_key_values=pkv, use_cache=True)
        logits = logits[:, -1, :] / req.temperature
        probs = torch.softmax(logits, dim=-1)
        nt = torch.multinomial(probs, num_samples=1)
        tt = decode([nt.item()])
        return nt, new_kv, tt

    next_token, past_kv, token_text = generate_stream_token(prompt_tensor, None, 0)
    full_raw_text += token_text
    all_token_texts.append(token_text)
    yield json.dumps({"choices": [{"delta": {"content": token_text}, "index": 0}]})

    x = torch.cat([prompt_tensor, next_token], dim=-1)

    for _ in range(req.max_tokens - 1):
        next_token, past_kv, token_text = generate_stream_token(next_token, past_kv, 1)
        full_raw_text += token_text
        all_token_texts.append(token_text)
        x = torch.cat([x, next_token], dim=-1)
        yield json.dumps({"choices": [{"delta": {"content": token_text}, "index": 0}]})
        await asyncio.sleep(0)

    # Check for tool suggestions (suggest then wait — no auto-execute)
    suggestions = agent.parse_tool_suggestions(full_raw_text)

    # Strip [TOOL: ...] patterns from display text
    clean_text = re.sub(r'\[TOOL:\s*(\w+)\(([^)]*)\)\]', '', full_raw_text).strip()

    # Save conversation memory
    agent.conversation_memory.add("user", prompt)
    agent.conversation_memory.add("assistant", clean_text)

    with _model_lock:
        agent.clear_lora()

    # If tool suggestions found, send them as structured data
    if suggestions:
        yield json.dumps({
            "choices": [{"delta": {"content": ""}, "index": 0, "finish_reason": "tool_suggestion"}],
            "tool_suggestions": suggestions,
        })

    yield json.dumps({"choices": [{"delta": {}, "finish_reason": "stop", "index": 0}]})
    yield "data: [DONE]"

@app.post("/v1/agent/identity/reset")
async def reset_identity():
    global agent
    if agent is None:
        raise HTTPException(503, "Agent not loaded")
    agent.identity = Identity(agent.d_model).to(device)
    return {"status": "reset", "identity_version": 0}

@app.post("/v1/agent/identity/save")
async def save_identity():
    global agent
    if agent is None:
        raise HTTPException(503, "Agent not loaded")
    path = os.environ.get("CORTEX_IDENTITY_PATH", "identity.pt")
    agent.save_identity(path)
    return {"status": "saved", "path": path}


@app.get("/v1/models")
async def list_models():
    return ModelList(data=[
        ModelInfo(id="cortex-core", created=int(time.time())),
    ])


# --- User management endpoints ---

@app.get("/v1/users")
async def list_users():
    if user_store is None:
        return {"users": []}
    return {"users": user_store.list_users()}

@app.get("/v1/users/{user_id}")
async def get_user(user_id: str):
    if user_store is None:
        raise HTTPException(503, "User store not available")
    emb = user_store.get_embedding(user_id)
    conversations = user_store.get_recent_conversations(user_id, n=5)
    return {
        "user_id": user_id,
        "has_embedding": emb is not None,
        "has_lora": user_store.has_lora(user_id),
        "conversations": len(user_store.get_recent_conversations(user_id, n=10000)),
        "recent": conversations,
    }

@app.post("/v1/users/{user_id}/embed")
async def recompute_user_embedding(user_id: str):
    """Recompute user embedding from conversation history."""
    global user_store, model, tokenizer, device
    if user_store is None:
        raise HTTPException(503, "User store not available")
    conversations = user_store.get_recent_conversations(user_id)
    if not conversations:
        raise HTTPException(400, f"No conversations found for user {user_id}")
    emb = UserStore.compute_embedding_from_history(
        conversations, model, tokenizer, device,
    )
    user_store.save_embedding(user_id, emb)
    return {"status": "recomputed", "user_id": user_id, "from_conversations": len(conversations)}

@app.post("/v1/users/{user_id}/train-lora")
async def train_user_lora(user_id: str):
    if user_store is None:
        raise HTTPException(503, "User store not available")
    t = threading.Thread(target=_run_user_lora_training, args=(user_id,), daemon=True)
    t.start()
    return {"status": "training_started", "user_id": user_id}

@app.delete("/v1/users/{user_id}")
async def delete_user(user_id: str):
    if user_store is None:
        raise HTTPException(503, "User store not available")
    user_store.clear_user(user_id)
    return {"status": "deleted", "user_id": user_id}

# --- Chat completions ---

@app.post("/v1/chat/completions")
async def chat_completions(req: ChatCompletionRequest, raw_request: Request):
    global _request_counter, improvement_engine
    if model is None:
        raise HTTPException(503, "Model not loaded")

    task_emb = None
    if req.task:
        with _model_lock:
            task_emb = apply_task_lora(req.task)
    elif req.user_id and user_store is not None:
        with _model_lock:
            task_emb = apply_user_lora(req.user_id)

    try:
        prompt = format_prompt(req.messages)
        prompt_ids = encode(prompt)

        gen_kwargs = dict(
            max_new_tokens=req.max_tokens,
            temperature=req.temperature,
            top_k=int(req.top_p * 100) if req.top_p < 1.0 else 50,
            repetition_penalty=1.2,
        )

        if req.stream:
            return EventSourceResponse(stream_generate(prompt_ids, req, gen_kwargs))

        output_ids, gen_logits = model.generate(prompt_ids, **gen_kwargs)
        generated_ids = output_ids[:, prompt_ids.shape[1]:]
        generated = generated_ids[0].tolist()
        text = decode(generated)

        # Save conversation for user personalization
        if req.user_id and user_store is not None:
            user_store.add_conversation(req.user_id, prompt, text)
            # Trigger direct LoRA training every 5 conversations (background)
            n = len(user_store.get_recent_conversations(req.user_id, n=1000))
            prev = _user_lora_steps_since_train.get(req.user_id, 0)
            if n >= 5 and n - prev >= 5:
                _user_lora_steps_since_train[req.user_id] = n
                import functools
                t = threading.Thread(
                    target=_run_user_lora_training,
                    args=(req.user_id,),
                    daemon=True,
                )
                t.start()

        # Collect self-improvement data from accumulated logits (no redundant forward pass)
        if task_emb is not None and improvement_engine is not None and gen_logits is not None:
            shift_logits = gen_logits[:, :generated_ids.shape[1], :].contiguous()
            loss = F.cross_entropy(
                shift_logits.view(-1, shift_logits.shape[-1]),
                generated_ids.view(-1),
            ).item()
            improvement_engine.collect(task_emb, prompt_ids, generated_ids, loss)

            _request_counter += 1
            if _request_counter % _improvement_interval == 0 and improvement_engine.ready:
                t = threading.Thread(target=_run_improvement_step, daemon=True)
                t.start()

        return {
            "id": f"chatcmpl-{int(time.time())}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": req.model,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }],
            "usage": {
                "prompt_tokens": prompt_ids.shape[1],
                "completion_tokens": len(generated),
                "total_tokens": prompt_ids.shape[1] + len(generated),
            },
        }
    finally:
        if req.task or req.user_id:
            with _model_lock:
                clear_task_lora()


async def stream_generate(
    prompt_ids: torch.Tensor,
    req: ChatCompletionRequest,
    gen_kwargs: dict,
) -> AsyncGenerator[str, None]:
    yield json.dumps({"choices": [{"delta": {"role": "assistant"}, "index": 0}]})

    prompt_len = prompt_ids.shape[1]
    x = prompt_ids

    with _model_lock:
        logits, _, past_kv = model.forward(x, use_cache=True)
    probs = torch.softmax(logits[:, -1, :] / gen_kwargs["temperature"], dim=-1)
    next_token = torch.multinomial(probs, num_samples=1)
    x = torch.cat([x, next_token], dim=-1)

    token_text = decode([next_token.item()])
    yield json.dumps({"choices": [{"delta": {"content": token_text}, "index": 0}]})

    for _ in range(gen_kwargs["max_new_tokens"] - 1):
        with _model_lock:
            logits, _, past_kv = model.forward(next_token, past_key_values=past_kv, use_cache=True)

        if gen_kwargs["top_k"] > 0:
            values, _ = torch.topk(logits[:, -1, :], gen_kwargs["top_k"], dim=-1)
            logits[:, -1, :][logits[:, -1, :] < values[:, -1:]] = float("-inf")

        probs = torch.softmax(logits[:, -1, :] / gen_kwargs["temperature"], dim=-1)
        next_token = torch.multinomial(probs, num_samples=1)
        x = torch.cat([x, next_token], dim=-1)

        token_text = decode([next_token.item()])
        yield json.dumps({"choices": [{"delta": {"content": token_text}, "index": 0}]})

        await asyncio.sleep(0)

    yield json.dumps({"choices": [{"delta": {}, "finish_reason": "stop", "index": 0}]})
    yield "data: [DONE]"


# --- Startup & Shutdown ---
# Handled by lifespan() context manager above.


if __name__ == "__main__":
    import argparse
    import os

    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=str, default="", help="Path to model checkpoint")
    parser.add_argument("--hypernet-checkpoint", type=str, default="", help="Path to hypernetwork checkpoint")
    parser.add_argument("--quantize", type=str, default="none", choices=["none", "fp16", "int8"],
                        help="Quantization mode: none (fp32), fp16 (half), int8 (dynamic)")
    parser.add_argument("--improvement-dir", type=str, default="",
                        help="Directory for self-improvement checkpoints (disabled if empty)")
    parser.add_argument("--prompt-dir", type=str, default="",
                        help="Directory of prompt files to ingest as knowledge base")
    parser.add_argument("--identity-path", type=str, default="",
                        help="Path to load/save agent identity vector")
    parser.add_argument("--memory-path", type=str, default="memory.sqlite",
                        help="Path for agent fact memory SQLite database")
    parser.add_argument("--data-dir", type=str, default=str(Path(__file__).resolve().parents[3] / "cortex-train" / "data"))
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--host", type=str, default="127.0.0.1")
    args = parser.parse_args()

    if args.host not in ("127.0.0.1", "localhost"):
        logger.warning(
            "Server bound to %s — no authentication is configured. "
            "Anyone on the network can access the API. "
            "Use --host 127.0.0.1 to restrict to localhost.", args.host
        )

    os.environ["CORTEX_CHECKPOINT"] = args.checkpoint or ""
    os.environ["CORTEX_HYPERNET_CHECKPOINT"] = args.hypernet_checkpoint or ""
    os.environ["CORTEX_QUANTIZE"] = args.quantize
    os.environ["CORTEX_IMPROVEMENT_DIR"] = args.improvement_dir
    os.environ["CORTEX_KNOWLEDGE_BASE"] = ""
    os.environ["CORTEX_PROMPT_DIR"] = args.prompt_dir
    os.environ["CORTEX_IDENTITY_PATH"] = args.identity_path or ""
    os.environ["CORTEX_MEMORY_PATH"] = args.memory_path or "memory.sqlite"
    os.environ["CORTEX_DATA_DIR"] = args.data_dir

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
