#!/bin/bash
# Aura — one-command launch
# Defaults to Ollama if available, then distilled checkpoint, then GPT-2.
# Usage: bash serve.sh [--port PORT] [--model MODEL]

BASE="$(cd "$(dirname "$0")" && pwd)"
DISTILLED_CKPT="$BASE/aura-train/checkpoints/distilled_final.pt"

if command -v ollama &>/dev/null && ollama list &>/dev/null 2>&1; then
    echo "Ollama detected — using external model (configurable in Settings)."
    echo "  Fallback: distilled checkpoint → GPT-2 when Ollama is unavailable."
    exec bash "$BASE/aura-train/serve_pretrained.sh" "$@"
elif [ -f "$DISTILLED_CKPT" ]; then
    echo "No Ollama found — using distilled checkpoint."
    exec bash "$BASE/aura-train/serve_v2.sh" --checkpoint "$DISTILLED_CKPT" "$@"
else
    echo "No Ollama or distilled checkpoint — using GPT-2 fallback."
    exec bash "$BASE/aura-train/serve_pretrained.sh" "$@"
fi
