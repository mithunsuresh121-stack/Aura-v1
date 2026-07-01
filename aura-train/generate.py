import torch
import time
import sys
import json
from pathlib import Path
from tokenizers import Tokenizer
from model import UniversalDenseCore


def load_checkpoint(path: str, device: str = "cpu"):
    ckpt = torch.load(path, map_location=device)
    config = ckpt["config"]
    model = UniversalDenseCore(**config)
    model.load_state_dict(ckpt["model_state_dict"])
    model.to(device)
    model.eval()
    return model, config


def load_tokenizer(data_dir: str):
    path = Path(data_dir) / "tokenizer.json"
    if path.exists():
        return Tokenizer.from_file(str(path))
    return None


def encode(tokenizer, text: str) -> torch.Tensor:
    return torch.tensor([tokenizer.encode(text).ids], dtype=torch.long)


def decode(tokenizer, ids: list[int]) -> str:
    return tokenizer.decode(ids)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=str, default=None,
                        help="Optional checkpoint; uses random init if not set")
    parser.add_argument("--data-dir", type=str, default="data")
    parser.add_argument("--prompt", type=str, default="Once upon a time")
    parser.add_argument("--max-tokens", type=int, default=64)
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--top-k", type=int, default=40)
    parser.add_argument("--repetition-penalty", type=float, default=1.1)
    args = parser.parse_args()

    device = "cpu"

    if args.checkpoint:
        print(f"loading checkpoint: {args.checkpoint}")
        model, config = load_checkpoint(args.checkpoint, device)
    else:
        print("no checkpoint — using random init")
        model = UniversalDenseCore(d_model=768, n_layers=6)
        config = {"vocab_size": 16384}

    print(f"  model: {model.d_model}d, {model.n_layers} layers, {config.get('vocab_size', model.embedding.num_embeddings)} vocab")

    tokenizer = load_tokenizer(args.data_dir)
    if tokenizer is None:
        print("warning: no tokenizer found, showing raw IDs")

    prompt_ids = encode(tokenizer, args.prompt) if tokenizer else torch.randint(0, config.get("vocab_size", 16384), (1, 4))

    print(f'\nprompt: "{args.prompt}"')
    print("generating...")

    t0 = torch.cuda.Event(enable_timing=True) if torch.cuda.is_available() else None
    start = time.time()

    output, _ = model.generate(
        prompt_ids,
        max_new_tokens=args.max_tokens,
        temperature=args.temperature,
        top_k=args.top_k,
        repetition_penalty=args.repetition_penalty,
    )

    elapsed = time.time() - start

    if tokenizer:
        generated_text = decode(tokenizer, output[0].tolist())
        print(f'output: "{generated_text}"')
    else:
        print(f"output IDs: {output[0].tolist()}")

    gen_len = output.shape[1] - prompt_ids.shape[1]
    print(f"\n  generated {gen_len} tokens in {elapsed:.1f}s ({gen_len/elapsed:.1f} tok/s)")
