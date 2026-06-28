#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "============================================"
echo "  CORTEX — Local AI Agent Setup"
echo "============================================"
echo ""

# --- Check Python ---
PYTHON=""
for cmd in python3.11 python3.12 python3; do
    if command -v "$cmd" &>/dev/null; then
        PYTHON="$cmd"
        break
    fi
done
if [ -z "$PYTHON" ]; then
    echo "ERROR: Python 3.11+ is required. Install from https://www.python.org/downloads/"
    exit 1
fi
echo "[✓] Python: $($PYTHON --version)"

# --- Check Node.js ---
if ! command -v node &>/dev/null; then
    echo "ERROR: Node.js 18+ is required. Install from https://nodejs.org/"
    exit 1
fi
echo "[✓] Node.js: $(node --version)"

# --- Check Rust (for Tauri build, optional) ---
HAS_RUST=false
if command -v cargo &>/dev/null; then
    HAS_RUST=true
    echo "[✓] Rust: $(rustc --version)"
else
    echo "[ ] Rust: not found (Tauri desktop build skipped — use Python server instead)"
fi

# --- Install Python dependencies ---
echo ""
echo "--- Installing Python dependencies ---"
$PYTHON -m pip install --upgrade pip -q
$PYTHON -m pip install -r "$SCRIPT_DIR/cortex-train/requirements.txt" -q
$PYTHON -m pip install fastapi uvicorn[standard] sse-starlette tokenizers -q
echo "[✓] Python packages installed"

# --- Install Node.js dependencies ---
echo ""
echo "--- Installing Node.js dependencies ---"
cd "$SCRIPT_DIR/cortex-app"
npm install --silent 2>/dev/null || npm install
echo "[✓] Node.js packages installed"

# --- Create data directory ---
mkdir -p "$SCRIPT_DIR/cortex-train/data"

# --- Download pre-trained model (if available) ---
echo ""
echo "--- Model setup ---"
MODEL_DIR="$SCRIPT_DIR/cortex-train/checkpoints"
mkdir -p "$MODEL_DIR"

if [ ! -f "$MODEL_DIR/final.pt" ]; then
    echo "No pre-trained model found. Run 'bash download_model.sh' to download a checkpoint,"
    echo "or train your own with: cd cortex-train && $PYTHON train_v2.py"
else
    echo "[✓] Model checkpoint found: $MODEL_DIR/final.pt"
fi

# --- Train or download tokenizer ---
if [ ! -f "$SCRIPT_DIR/cortex-train/data/tokenizer.json" ]; then
    echo "No tokenizer found. Run the Colab notebook (colab_train.ipynb) to train one."
    # Create a minimal tokenizer as fallback
    $PYTHON -c "
from tokenizers import Tokenizer, models, trainers
tok = Tokenizer(models.BPE(unk_token='[UNK]'))
trainer = trainers.BpeTrainer(vocab_size=4096, special_tokens=['[UNK]', '[CLS]', '[SEP]', '[PAD]'])
trainer2 = trainers.BpeTrainer(vocab_size=4096, special_tokens=['[UNK]', '[CLS]', '[SEP]', '[PAD]'])
# Train on tiny sample
tok.train_from_iterator([
    'Hello, how are you today? Cortez AI assistant at your service. ' * 1000
], trainer=trainer2)
tok.save('$SCRIPT_DIR/cortex-train/data/tokenizer.json')
print('[i] Created fallback tokenizer (vocab_size=4096)')
" 2>/dev/null && echo "[i] Fallback tokenizer created" || echo "[!] Could not create fallback tokenizer"
fi

# --- Build frontend ---
echo ""
echo "--- Building frontend ---"
cd "$SCRIPT_DIR/cortex-app"
npx vite build --silent 2>/dev/null || npx vite build
echo "[✓] Frontend built"

echo ""
echo "============================================"
echo "  Setup complete!"
echo "============================================"
echo ""
echo "Start the server:"
echo "  cd $(pwd) && $PYTHON cortex-core/src/server/main.py"
echo ""
echo "Start the frontend (dev mode):"
echo "  cd cortex-app && npm run dev"
echo ""
echo "Or use the convenience script:"
echo "  bash start.sh"
echo ""
