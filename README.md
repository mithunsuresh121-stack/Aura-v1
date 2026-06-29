# Aura — Local-First AI Agent

A hybrid AI product: free local inference + premium cloud subscription. Built around a custom transformer architecture (UniversalDenseCore) with per-user LoRA personalization.

**Status:** Active development. Local tier uses GPT-2 as backbone; custom model via knowledge distillation in progress.

## Architecture

```
User (Chat UI)  <-->  FastAPI Server (OpenAI-compatible API)
                          |
                    +-----+--------+
                    |              |
              Agent Layer    User Store
                    |
          +---------+----------+
          |         |          |
     Identity   Knowledge   Memory
          |         |
    HyperNetwork   RAG Ingestion
          |
     LoRA Adapter
          |
   UniversalDenseCore (custom transformer)
```

## Directory Structure

| Directory | Purpose |
|---|---|
| `cortex-core/` | Python backend — FastAPI server, agent logic, per-user memory, personalization |
| `cortex-train/` | Model definition, training, data prep, knowledge distillation scripts |
| `cortex-rag/` | Retrieval-Augmented Generation — prompt ingestion and vector indexing |
| `cortex-app/` | Frontend — Vue 3 + Vite web app, Tauri v2 desktop shell |

## Quick Start

### Prerequisites

- Python 3.9
- Node.js 18+

### Local Inference (GPT-2)

```bash
bash serve.sh --port 8081
```

This starts an OpenAI-compatible API at `http://127.0.0.1:8081`:

```bash
curl http://127.0.0.1:8081/health

curl -X POST http://127.0.0.1:8081/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Hello"}],"user_id":"me"}'
```

### Full Stack (Web UI + Server)

```bash
bash start.sh
```

### Training

Training scripts and Kaggle notebooks are in `cortex-train/`:

- `kaggle_distill.ipynb` — Knowledge distillation (GPT-2 → UniversalDenseCore) on Kaggle T4 GPU
- `kaggle_train.ipynb` — Pre-training the custom model from scratch
- `distill.py` — Standalone distillation script
- `train_v2.py` — Standalone training script

## Key Components

- **UniversalDenseCore** — Custom transformer with RoPE, RMSNorm, SwiGLU, KV-caching. Configurable vocab, layers, heads, dimensions.
- **HyperNetwork** — MLP that generates LoRA adapter weights from task embeddings. Core of the personalization system.
- **Per-User Memory** — Conversation history stored in JSONL files, loaded as context for each user.
- **RAG Pipeline** — Ingests prompts/markdown/text, chunks, embeds, indexes for retrieval.
- **OpenAI-Compatible API** — Drop-in replacement for OpenAI client libraries.

## Roadmap

1. ✅ Local GPT-2 server with per-user memory
2. 🔄 Knowledge distillation (training 50M parameter student on Kaggle)
3. ⏳ Switch local tier to distilled custom model
4. ⏳ Wire Tauri desktop app to server
5. ⏳ Cloud premium tier with larger models
