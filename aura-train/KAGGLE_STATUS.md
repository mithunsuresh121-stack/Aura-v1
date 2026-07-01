# Kaggle Distillation Status

## Goal
Distill GPT-2 (124M) → UniversalDenseCore student (59M) using KL divergence on TinyStories.

## Last Run
- **Status:** 20,567 / 30,000 steps (69%) — interrupted before completion
- **Hardware:** Kaggle T4 GPU
- **Duration:** ~5 hours elapsed
- **Checkpoints saved:** step_05000, step_10000, step_15000, step_20000

## Loss Curve
| Step | Total Loss | KL Loss | CE Loss |
|------|-----------|---------|---------|
| 5,000  | 109.90 | 106.80 | — |
| 10,000 | 77.66  | 75.05  | — |
| 15,000 | 56.23  | 53.93  | — |
| 20,000 | 49.49  | 47.38  | — |
| 20,567 | 47.60  | 45.55  | — |

Loss trending down steadily — model was learning.

## Config
```
--steps 30000 --batch-size 8 --seq-len 256 --lr 1e-4 --temp 4.0
--d-model 512 --n-layers 8 --n-heads 8 --d-ff 2048
```

## To Resume
On Kaggle, upload `kaggle_distill.ipynb`, modify the command to:
```
!python distill.py \
    --steps 30000 \
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

## After Completion
1. Download `distilled_final.pt` (~200MB) from Kaggle
2. Copy to `aura-train/checkpoints/`
3. Wire into server to replace GPT-2
4. Compare generation quality
