#!/bin/bash
# Launch the Cortex server with the newly trained model (checkpoints).
# Usage: ./serve_v2.sh [--port PORT] [--host HOST]
BASE="$(cd "$(dirname "$0")/.." && pwd)"
CKPT_DIR="$BASE/aura-train/checkpoints"
DATA_DIR="$BASE/aura-train/data"
SERVER="$BASE/aura-core/src/server/main.py"

# Pick the best available checkpoint
if [ -f "$CKPT_DIR/distilled_final.pt" ]; then
    CKPT="$CKPT_DIR/distilled_final.pt"
elif [ -f "$CKPT_DIR/best.pt" ]; then
    CKPT="$CKPT_DIR/best.pt"
elif [ -f "$CKPT_DIR/final.pt" ]; then
    CKPT="$CKPT_DIR/final.pt"
else
    echo "ERROR: No checkpoint found in $CKPT_DIR"
    echo "Training may still be running. Check: ./monitor_training.sh"
    exit 1
fi

echo "Starting server with:"
echo "  checkpoint: $CKPT"
echo "  data-dir:   $DATA_DIR"

USER_DIR="$BASE/aura-core/users"
mkdir -p "$USER_DIR"

python3.9 "$SERVER" \
    --checkpoint "$CKPT" \
    --data-dir "$DATA_DIR" \
    --improvement-dir "$CKPT_DIR/improvement" \
    "$@"
