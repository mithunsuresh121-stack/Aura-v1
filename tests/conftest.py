"""pytest config: add project source to sys.path."""
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "aura-core" / "src"
TRAIN = Path(__file__).resolve().parents[1] / "aura-train"
RAG = Path(__file__).resolve().parents[1] / "aura-rag"

for p in [SRC, TRAIN, RAG]:
    if p.exists() and str(p) not in sys.path:
        sys.path.insert(0, str(p))
