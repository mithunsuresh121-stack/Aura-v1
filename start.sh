#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "Starting AURA..."
echo ""

# Launch server in background
echo "  Server : http://127.0.0.1:8081"
echo ""

bash "$SCRIPT_DIR/serve.sh" --port 8081 &
SERVER_PID=$!

sleep 3

# Start frontend dev server
cd "$SCRIPT_DIR/aura-app"
npx vite --host 127.0.0.1 --port 5173 &
VITE_PID=$!

echo ""
echo "  App    : http://127.0.0.1:5173"
echo "  API    : http://127.0.0.1:8081"
echo ""
echo "Press Ctrl+C to stop both"
echo ""

trap "kill $SERVER_PID $VITE_PID 2>/dev/null; exit" INT TERM
wait
