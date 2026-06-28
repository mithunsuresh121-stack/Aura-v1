#!/bin/bash
# Launch a pretrained HuggingFace model with the same API as the cortex server.
# Usage: ./serve_pretrained.sh [--model MODEL] [--port PORT]
#
# Default model: TinyLlama-1.1B (runs on CPU, ~2-3GB RAM, ~10 tok/s)
# Other options:
#   --model "TinyLlama/TinyLlama-1.1B-Chat-v1.0"  (1.1B params, best quality)
#   --model "microsoft/phi-1_5"                     (1.3B params)
#   --model "Qwen/Qwen2.5-0.5B-Instruct"            (0.5B params, fastest)

BASE="$(cd "$(dirname "$0")/.." && pwd)"
SERVER="$BASE/cortex-core/src/server/pretrained_server.py"

# Default: GPT-2 (124M params, ~500MB, 3-5 tok/s on CPU — fastest for Intel Macs)
# Alternatives:
#   Qwen/Qwen2.5-0.5B-Instruct              (0.5B params, ~1GB, 0.5 tok/s)
#   TinyLlama/TinyLlama-1.1B-Chat-v1.0      (1.1B params, ~2GB, 0.2 tok/s)
#   microsoft/phi-1_5                        (1.3B params, ~2.5GB, 0.2 tok/s)
MODEL="${CORTEX_PRETRAINED_MODEL:-gpt2}"

echo "Starting pretrained model server:"
echo "  model: $MODEL"

python3 "$SERVER" \
    --model "$MODEL" \
    "$@"
