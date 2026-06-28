import os
os.environ["OMP_NUM_THREADS"] = "2"
os.environ["MKL_NUM_THREADS"] = "2"

import torch
torch.set_num_threads(2)
import torch.optim as optim
from torch.utils.data import DataLoader, Dataset
import time
import json
import math
import numpy as np
from pathlib import Path
from tqdm import tqdm

from model import UniversalDenseCore


class TextDataset(Dataset):
    def __init__(self, data: list[int], seq_len: int = 256):
        self.data = torch.tensor(data, dtype=torch.long)
        self.seq_len = seq_len

    def __len__(self):
        return (len(self.data) - 1) // self.seq_len

    def __getitem__(self, idx):
        start = idx * self.seq_len
        x = self.data[start:start + self.seq_len]
        y = self.data[start + 1:start + self.seq_len + 1]
        return x, y


def forward_backward(model, x, y, beta=0.01, accum_steps=1):
    model.train()
    logits, info, _ = model(x)
    loss = model.compute_loss(logits, y, info, beta)
    (loss / accum_steps).backward()
    return loss.item()


@torch.no_grad()
def validate(model, loader, beta=0.01, device="cpu"):
    model.eval()
    total_loss = 0.0
    n_batches = 0
    for x, y in loader:
        x, y = x.to(device), y.to(device)
        logits, info, _ = model(x)
        loss = model.compute_loss(logits, y, info, beta)
        total_loss += loss.item()
        n_batches += 1
    return total_loss / max(n_batches, 1)


def save_checkpoint(model, path, step, loss, config):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    torch.save({
        "step": step,
        "model_state_dict": model.state_dict(),
        "loss": loss,
        "config": config,
    }, path)


def load_data(data_dir: str, seq_len: int):
    data_dir = Path(data_dir)
    config_path = data_dir / "config.json"
    tokens_path = data_dir / "tokens.npy"

    if config_path.exists():
        with open(config_path) as f:
            data_config = json.load(f)
        print(f"  dataset: {data_config.get('dataset', 'unknown')}")
        print(f"  total tokens: {data_config.get('total_tokens', 0):,}")
        print(f"  vocab_size: {data_config.get('vocab_size', 0)}")
    else:
        data_config = {}

    tokens = np.load(tokens_path)
    print(f"  loaded {len(tokens):,} tokens")

    return tokens.tolist(), data_config


def get_cosine_schedule_with_warmup(optimizer, warmup_steps, total_steps):
    def lr_lambda(step):
        if step < warmup_steps:
            return step / max(1, warmup_steps)
        progress = (step - warmup_steps) / max(1, total_steps - warmup_steps)
        return 0.5 * (1.0 + math.cos(math.pi * progress))
    return torch.optim.lr_scheduler.LambdaLR(optimizer, lr_lambda)


def format_time(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h}h {m}m {s}s"


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=str, default="data")
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--grad-accum", type=int, default=1)
    parser.add_argument("--seq-len", type=int, default=256)
    parser.add_argument("--lr", type=float, default=3e-4)
    parser.add_argument("--beta", type=float, default=0.01)
    parser.add_argument("--steps", type=int, default=30000)
    parser.add_argument("--warmup", type=int, default=1000)
    parser.add_argument("--save-every", type=int, default=5000)
    parser.add_argument("--val-every", type=int, default=500)
    parser.add_argument("--checkpoint-dir", type=str, default="checkpoints")
    parser.add_argument("--resume", type=str, default=None)
    parser.add_argument("--d-model", type=int, default=320)
    parser.add_argument("--n-layers", type=int, default=6)
    parser.add_argument("--n-heads", type=int, default=10)
    parser.add_argument("--d-ff", type=int, default=1280)
    parser.add_argument("--max-steps", type=int, default=4)
    args = parser.parse_args()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"device: {device}")

    data_tokens, data_config = load_data(args.data_dir, args.seq_len)
    vocab_size = data_config.get("vocab_size", 16384)

    model_config = dict(
        vocab_size=vocab_size,
        d_model=args.d_model,
        n_heads=args.n_heads,
        d_ff=args.d_ff,
        n_layers=args.n_layers,
        max_steps=args.max_steps,
        max_seq_len=2048,
        dropout=0.0,
    )

    model = UniversalDenseCore(**model_config)
    total_params = sum(p.numel() for p in model.parameters())
    print(f"model params: {total_params:,}")
    print(f"model config: vocab_size={vocab_size}, d_model={args.d_model}, layers={args.n_layers}")

    if args.resume:
        ckpt = torch.load(args.resume, map_location=device)
        model.load_state_dict(ckpt["model_state_dict"])
        print(f"resumed from step {ckpt['step']}")

    model.to(device)

    dataset = TextDataset(data_tokens, args.seq_len)
    split = int(0.95 * len(dataset))
    train_ds = torch.utils.data.Subset(dataset, range(split))
    val_ds = torch.utils.data.Subset(dataset, range(split, len(dataset)))
    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True)
    val_loader = DataLoader(val_ds, batch_size=args.batch_size)

    optimizer = optim.AdamW(model.parameters(), lr=args.lr, weight_decay=0.1)
    scheduler = get_cosine_schedule_with_warmup(optimizer, args.warmup, args.steps)

    print(f"train samples: {len(train_ds):,}, val samples: {len(val_ds):,}")
    print(f"training for {args.steps} steps\n")

    start_step = 0
    if args.resume:
        ckpt_data = torch.load(args.resume, map_location="cpu")
        start_step = ckpt_data.get("step", 0)

    best_val_loss = float("inf")
    step = start_step
    batch_iter = iter(train_loader)
    t_start = time.time()

    progress = tqdm(total=args.steps - start_step, desc="training", unit="step")

    try:
        while step < args.steps:
            optimizer.zero_grad()
            accum_loss = 0.0
            for _ in range(args.grad_accum):
                try:
                    x, y = next(batch_iter)
                except StopIteration:
                    batch_iter = iter(train_loader)
                    x, y = next(batch_iter)
                accum_loss += forward_backward(model, x.to(device), y.to(device), args.beta, args.grad_accum)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            scheduler.step()
            step += 1
            progress.update(1)
            progress.set_postfix(loss=f"{accum_loss / args.grad_accum:.4f}")

            if step > 0 and step % args.val_every == 0:
                val_loss = validate(model, val_loader, args.beta, device)
                elapsed = time.time() - t_start
                eta = (elapsed / (step - start_step)) * (args.steps - step) if step > start_step else 0
                progress.write(
                    f"step {step:6d} | loss {accum_loss / args.grad_accum:.4f} | val {val_loss:.4f} "
                    f"| elapsed {format_time(elapsed)} | ETA {format_time(eta)}"
                )
                if val_loss < best_val_loss:
                    best_val_loss = val_loss
                    save_checkpoint(model, os.path.join(args.checkpoint_dir, "best.pt"), step, val_loss, model_config)
                    progress.write(f"  ✓ new best val loss")

            if step > 0 and step % args.save_every == 0:
                save_checkpoint(
                    model,
                    os.path.join(args.checkpoint_dir, f"step_{step:06d}.pt"),
                    step, accum_loss / args.grad_accum, model_config,
                )

    except KeyboardInterrupt:
        progress.write("\ntraining interrupted")

    progress.close()
    save_checkpoint(model, os.path.join(args.checkpoint_dir, "final.pt"), step, accum_loss / args.grad_accum, model_config)
    total_time = time.time() - t_start
    print(f"\ntraining complete: {format_time(total_time)}")
