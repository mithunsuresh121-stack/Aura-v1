#!/bin/bash
# Aura — one-command launch
# Starts the GPT-2 server with per-user memory on port 8081.
# Usage: bash serve.sh [--port PORT] [--model MODEL]

BASE="$(cd "$(dirname "$0")" && pwd)"
exec bash "$BASE/cortex-train/serve_pretrained.sh" "$@"
