# Kaggle Distillation — Master Status

## Goal
Distill GPT-2 (124M teacher) → UniversalDenseCore (59M student) using KL divergence on TinyStories. Result: a fast, on-device model we control.

---

## Architecture

| Component | Details |
|-----------|---------|
| **Teacher** | GPT-2 (124M params), frozen |
| **Student** | UniversalDenseCore (59M params), custom transformer |
| **Student config** | `d_model=512, n_layers=8, n_heads=8, d_ff=2048` |
| **Tokenizer** | GPT-2 tokenizer (vocab 50257) |
| **Dataset** | `roneneldan/TinyStories`, streamed, seq_len=256 |
| **Loss** | KL divergence (temp=4.0) + CE (for stability) |

### Files
| File | Purpose |
|------|---------|
| `model.py` | UniversalDenseCore — RoPE, RMSNorm, dense core transformer |
| `hypernetwork.py` | Hypernetwork conditioning (not used in distill) |
| `distill.py` | Distillation script with `--resume` support |
| `kaggle_distill.ipynb` | Kaggle notebook — upload this to Kaggle |
| `kaggle_train.ipynb` | Pre-training from scratch (separate experiment) |
| `train_v2.py` | Local CPU pre-training |
| `MASTER_STATUS.md` | ← This file |

---

## Latest Run (In Progress)

**Status:** Running fresh on Kaggle — 25K steps, ~4.2h estimate
**Started:** `--steps 25000 --batch-size 8 --seq-len 256 --lr 1e-4 --temp 4.0`

**Previous run (lost due to session crash):** 20,567 / 30,000 steps
- Loss curve: 109.9 → 47.6 (steady improvement)
- Checkpoints saved every 5K (all lost with session)

---

## How to Run on Kaggle

1. Go to [kaggle.com](https://kaggle.com) → Create → New Notebook
2. **Settings → Accelerator → GPU T4**
3. **Settings → Internet → ON**
4. Upload `kaggle_distill.ipynb` or paste cells
5. Run All — runs Option A (25K steps fresh)

### Option A (fresh run)
```bash
!python distill.py \
    --steps 25000 \
    --batch-size 8 \
    --seq-len 256 \
    --lr 1e-4 \
    --temp 4.0 \
    --save-every 5000 \
    --checkpoint-dir distilled_checkpoints \
    --d-model 512 \
    --n-layers 8 \
    --n-heads 8 \
    --d-ff 2048
```

### Option B (resume from crash)
```python
# Auto-finds latest checkpoint
import glob
ckpts = sorted(glob.glob('distilled_checkpoints/distilled_step_*.pt'))
latest = ckpts[-1]
```
```bash
!python distill.py \
    --steps 25000 \
    --resume {latest} \
    # ... same args as above
```

---

## After Distillation Completes

### 1. Download checkpoint
- Kaggle file browser → `distilled_checkpoints/` → `distilled_final.pt` (~200MB)
- Copy to Mac: `cp distilled_final.pt aura-train/checkpoints/`

### 2. Wire into server
Modify `aura-core/src/server/` to load the distilled checkpoint:
```python
from model import UniversalDenseCore
ckpt = torch.load("aura-train/checkpoints/distilled_final.pt", map_location="cpu")
model = UniversalDenseCore(**ckpt["config"])
model.load_state_dict(ckpt["model_state_dict"])
```

### 3. Compare quality
Test same prompts against GPT-2 baseline and the distilled model.

---

## Docs Site (Separate Track)
Landing page + 8 feature docs pages at `aura-app/public/`:
- `/landing.html` — marketing page
- `/docs/index.html` — docs hub with sidebar navigation
- 7 feature pages: chat, computer-control, mcp, orchestration, video-editing, permissions, build

All served by Vite dev server at `localhost:5173`.
