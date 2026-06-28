#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "Starting CORTEX..."
echo ""

# Launch Python server in background
CORTEX_CHECKPOINT="${CORTEX_CHECKPOINT:-$SCRIPT_DIR/cortex-train/checkpoints/final.pt}"
CORTEX_DATA_DIR="${CORTEX_DATA_DIR:-$SCRIPT_DIR/cortex-train/data}"

echo "  Server : http://127.0.0.1:8080"
echo "  Model  : ${CORTEX_CHECKPOINT:-random init}"
echo "  Data   : $CORTEX_DATA_DIR"
echo ""

python3.9 "$SCRIPT_DIR/cortex-core/src/server/main.py" \
    --host 127.0.0.1 \
    --port 8080 \
    --checkpoint "$CORTEX_CHECKPOINT" &
SERVER_PID=$!

# Start frontend
cd "$SCRIPT_DIR/cortex-app"
npx vite --host 127.0.0.1 &
VITE_PID=$!

echo ""
echo "Press Ctrl+C to stop both server and frontend"
echo ""

trap "kill $SERVER_PID $VITE_PID 2>/dev/null; exit" INT TERM
wait
