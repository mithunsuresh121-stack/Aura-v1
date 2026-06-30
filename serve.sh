#!/bin/bash
# Aura — one-command launch
# Starts the distilled student model server on port 8081.
# Falls back to GPT-2 if no distilled checkpoint is available.
# Usage: bash serve.sh [--port PORT] [--model MODEL]

BASE="$(cd "$(dirname "$0")" && pwd)"
DISTILLED_CKPT="$BASE/cortex-train/checkpoints/distilled_final.pt"

if [ -f "$DISTILLED_CKPT" ]; then
    exec bash "$BASE/cortex-train/serve_v2.sh" --checkpoint "$DISTILLED_CKPT" "$@"
else
    exec bash "$BASE/cortex-train/serve_pretrained.sh" "$@"
fi
