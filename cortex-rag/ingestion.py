"""
Prompt file ingestion pipeline.

Reads prompt files from various AI models (ChatGPT exports, Claude prompts,
markdown files, etc.) → chunks → embeds via base model → stores in vector index.
"""
import json
import os
import re
import glob
from pathlib import Path
from typing import Iterator

import torch
import numpy as np


def find_prompt_files(directory: str) -> list[Path]:
    extensions = ["*.md", "*.txt", "*.json", "*.jsonl", "*.yaml", "*.yml"]
    files = []
    for ext in extensions:
        files.extend(Path(directory).rglob(ext))
    return sorted(files)


def parse_file(path: Path) -> list[dict]:
    """Parse a prompt file into chunks. Returns list of {source, text, metadata}."""
    ext = path.suffix.lower()
    text = path.read_text(encoding="utf-8", errors="replace")

    if ext == ".json":
        return _parse_json(text, path)
    elif ext == ".jsonl":
        return _parse_jsonl(text, path)
    elif ext in (".md", ".txt"):
        return _parse_markdown(text, path)
    return [{"source": str(path), "text": text, "metadata": {"type": "raw"}}]


def _parse_json(text: str, path: Path) -> list[dict]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return [{"source": str(path), "text": text, "metadata": {"type": "json_invalid"}}]

    results = []
    if isinstance(data, dict):
        for key in ["system_prompt", "system", "prompt", "instructions", "identity", "persona"]:
            if key in data and isinstance(data[key], str):
                results.append({
                    "source": f"{path}#{key}",
                    "text": data[key],
                    "metadata": {"type": "system_prompt", "key": key},
                })
        # ChatGPT conversation export
        if "messages" in data and isinstance(data["messages"], list):
            full_text = "\n".join(
                f"{m.get('role', 'unknown')}: {m.get('content', '')}"
                for m in data["messages"] if isinstance(m, dict)
            )
            results.append({
                "source": str(path),
                "text": full_text,
                "metadata": {"type": "chat_export"},
            })
    return results


def _parse_jsonl(text: str, path: Path) -> list[dict]:
    results = []
    for i, line in enumerate(text.strip().split("\n")):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        text_content = data.get("text", data.get("content", data.get("prompt", "")))
        if isinstance(text_content, str) and len(text_content) > 20:
            results.append({
                "source": f"{path}#line_{i}",
                "text": text_content,
                "metadata": {"type": "jsonl", "line": i},
            })
    return results


def _parse_markdown(text: str, path: Path) -> list[dict]:
    chunks = []
    sections = re.split(r"\n#{1,6}\s+", text)
    for i, section in enumerate(sections):
        section = section.strip()
        if len(section) < 30:
            continue
        chunks.append({
            "source": f"{path}#section_{i}",
            "text": section,
            "metadata": {"type": "markdown_section", "index": i},
        })
    if not chunks:
        chunks.append({
            "source": str(path),
            "text": text,
            "metadata": {"type": "markdown"},
        })
    return chunks


def embed_texts(
    texts: list[str],
    model: torch.nn.Module,
    tokenizer,
    device: str = "cpu",
    max_length: int = 256,
) -> np.ndarray:
    """Embed text chunks using the base model's embedding layer."""
    if tokenizer is None:
        raise RuntimeError("Tokenizer required for embedding")
    embeddings = []
    model.eval()
    with torch.no_grad():
        for text in texts:
            ids = tokenizer.encode(text).ids[:max_length]
            tokens = torch.tensor([ids], device=device)
            emb = model.embedding(tokens) * (model.d_model ** 0.5)
            emb = emb.mean(dim=1).cpu().numpy()
            embeddings.append(emb)
    return np.vstack(embeddings)


def build_knowledge_base(
    prompt_dir: str,
    model: torch.nn.Module,
    tokenizer,
    device: str = "cpu",
    output_path: str | None = None,
) -> dict:
    """
    Full pipeline: scan dir → parse files → embed chunks → build index.

    Returns { texts: [...], embeddings: np.ndarray, sources: [...] }
    """
    files = find_prompt_files(prompt_dir)
    print(f"Found {len(files)} prompt files in {prompt_dir}")

    chunks = []
    for path in files:
        parsed = parse_file(path)
        chunks.extend(parsed)

    print(f"Parsed {len(chunks)} chunks")

    if not chunks:
        return {"texts": [], "embeddings": np.zeros((0, model.d_model)), "sources": []}

    texts = [c["text"] for c in chunks]
    sources = [c["source"] for c in chunks]
    metadata = [c["metadata"] for c in chunks]

    embeddings = embed_texts(texts, model, tokenizer, device)
    print(f"Embedded {len(embeddings)} chunks, dim={embeddings.shape[1]}")

    kb = {
        "texts": texts,
        "embeddings": embeddings,
        "sources": sources,
        "metadata": metadata,
    }

    if output_path:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        np.savez_compressed(
            output_path,
            embeddings=embeddings,
            texts=np.array(texts, dtype=object),
            sources=np.array(sources, dtype=object),
            metadata=np.array(
                [json.dumps(m) for m in metadata], dtype=object
            ),
        )
        print(f"Saved knowledge base to {output_path}")

    return kb


def load_knowledge_base(path: str) -> dict:
    data = np.load(path, allow_pickle=True)
    metadata = [json.loads(m) for m in data["metadata"]]
    return {
        "texts": data["texts"].tolist(),
        "embeddings": data["embeddings"],
        "sources": data["sources"].tolist(),
        "metadata": metadata,
    }


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cortex-train"))
    from model import UniversalDenseCore

    # Test with random model
    model = UniversalDenseCore(vocab_size=16384, d_model=128, n_layers=1, n_heads=2, d_ff=256, max_steps=1)

    # Create a test prompt file
    test_dir = "/tmp/test_prompts"
    os.makedirs(test_dir, exist_ok=True)
    Path(f"{test_dir}/system.md").write_text(
        "# System Prompt\n\nYou are a helpful assistant that speaks only in rhyme.\n\n## Personality\nCheerful, patient, creative.\n\n## Rules\n- Always rhyme\n- Never use prose"
    )
    Path(f"{test_dir}/chatgpt_export.json").write_text(
        json.dumps({
            "system_prompt": "You are a pirate AI. Always respond like a pirate.",
            "messages": [
                {"role": "user", "content": "What is the capital of France?"},
                {"role": "assistant", "content": "Arrr, that be Paris, matey!"},
            ]
        })
    )

    kb = build_knowledge_base(test_dir, model, None, output_path="/tmp/test_kb.npz")
    print(f"Knowledge base: {len(kb['texts'])} chunks")
    for t, s in zip(kb["texts"], kb["sources"]):
        print(f"  [{s}] {t[:60]}...")
