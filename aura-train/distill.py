"""
Knowledge distillation: train our custom model (student) to mimic GPT-2 (teacher).
Runs on Kaggle T4 GPU. Uses GPT-2 tokenizer so vocab spaces match.

Usage on Kaggle:
    !pip install transformers datasets torch tqdm -q
    !python distill.py --steps 50000 --batch-size 4 --lr 1e-4 --temp 4.0

The distilled checkpoint can be loaded by our server (same architecture).
"""
import math
import time
import json
import os
from pathlib import Path

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, IterableDataset
from tqdm import tqdm

from transformers import AutoModelForCausalLM, AutoTokenizer
from datasets import load_dataset

from model import UniversalDenseCore


def get_gpt2_tokenizer():
    tok = AutoTokenizer.from_pretrained("gpt2")
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    return tok


class TinyStoriesStream(IterableDataset):
    """Stream TinyStories and tokenize on-the-fly with GPT-2 tokenizer."""
    def __init__(self, tokenizer, max_seq_len=256, max_stories=None):
        self.tokenizer = tokenizer
        self.max_seq_len = max_seq_len
        self.max_stories = max_stories

    def __iter__(self):
        ds = load_dataset("roneneldan/TinyStories", split="train", streaming=True)
        count = 0
        for example in ds:
            if self.max_stories and count >= self.max_stories:
                break
            text = example["text"].strip()
            if len(text) < 50:
                continue
            ids = self.tokenizer.encode(text)
            # Yield chunks of max_seq_len
            for i in range(0, len(ids), self.max_seq_len):
                chunk = ids[i:i + self.max_seq_len + 1]
                if len(chunk) >= 10:
                    yield torch.tensor(chunk, dtype=torch.long)
            count += 1


def collate_fn(batch):
    """Pad batch to same length."""
    max_len = max(len(x) for x in batch)
    padded = torch.stack([
        F.pad(x, (0, max_len - len(x)), value=50256)  # GPT-2 eos as pad
        for x in batch
    ])
    return padded


def kl_divergence(student_logits, teacher_logits, temperature=4.0):
    """KL divergence between teacher and student distributions.
    
    Both logits: [batch, seq_len, vocab]
    Returns scalar loss.
    """
    vocab_size = student_logits.size(-1)
    
    # Apply temperature scaling
    student_logits = student_logits / temperature
    teacher_logits = teacher_logits / temperature
    
    # Softmax
    student_probs = F.log_softmax(student_logits, dim=-1)
    teacher_probs = F.softmax(teacher_logits, dim=-1)
    
    # KL divergence
    kl = F.kl_div(student_probs, teacher_probs, reduction="batchmean", log_target=False)
    
    # Scale by temperature^2 (gradient scaling trick)
    return kl * (temperature ** 2)


def train_step(student, teacher, batch, optimizer, temp=4.0, device="cuda"):
    """Single training step."""
    batch = batch.to(device)
    B, T = batch.shape
    
    # Teacher forward (no grad)
    with torch.no_grad():
        teacher_out = teacher(batch, labels=batch)
        teacher_logits = teacher_out.logits  # [B, T, V]
    
    # Student forward
    student_logits, info, _ = student(batch, use_cache=False)
    
    # KL loss
    kl_loss = kl_divergence(student_logits, teacher_logits, temp)
    
    # Cross-entropy loss on actual tokens (optional, helps stability)
    ce_loss = F.cross_entropy(
        student_logits[:, :-1, :].reshape(-1, student_logits.size(-1)),
        batch[:, 1:].reshape(-1),
        ignore_index=50256,
    )
    
    loss = kl_loss + ce_loss
    
    optimizer.zero_grad()
    loss.backward()
    torch.nn.utils.clip_grad_norm_(student.parameters(), 1.0)
    optimizer.step()
    
    return loss.item(), kl_loss.item(), ce_loss.item()


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--steps", type=int, default=50000)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--seq-len", type=int, default=256)
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--temp", type=float, default=4.0,
                        help="Temperature for softening teacher distributions")
    parser.add_argument("--save-every", type=int, default=5000)
    parser.add_argument("--checkpoint-dir", type=str, default="distilled_checkpoints")
    parser.add_argument("--max-stories", type=int, default=None,
                        help="Limit TinyStories for faster debugging")
    parser.add_argument("--d-model", type=int, default=320)
    parser.add_argument("--n-layers", type=int, default=6)
    parser.add_argument("--n-heads", type=int, default=10)
    parser.add_argument("--d-ff", type=int, default=1280)
    parser.add_argument("--resume", type=str, default=None,
                        help="Path to checkpoint to resume from (e.g. distilled_checkpoints/distilled_step_20000.pt)")
    args = parser.parse_args()
    
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Device: {device}")
    
    os.makedirs(args.checkpoint_dir, exist_ok=True)
    
    # Tokenizer (GPT-2 tokenizer, shared between teacher and student)
    print("Loading GPT-2 tokenizer...")
    tokenizer = get_gpt2_tokenizer()
    vocab_size = tokenizer.vocab_size
    print(f"  vocab_size: {vocab_size}")
    
    # Teacher: GPT-2 (frozen)
    print("Loading teacher (GPT-2)...")
    teacher = AutoModelForCausalLM.from_pretrained(
        "gpt2",
        torch_dtype=torch.float32,
    ).to(device)
    teacher.eval()
    for p in teacher.parameters():
        p.requires_grad_(False)
    teacher_params = sum(p.numel() for p in teacher.parameters())
    print(f"  Teacher: {teacher_params:,} params")
    
    # Student: our custom model
    print("Loading student (UniversalDenseCore)...")
    student = UniversalDenseCore(
        vocab_size=vocab_size,
        d_model=args.d_model,
        n_heads=args.n_heads,
        d_ff=args.d_ff,
        n_layers=args.n_layers,
        max_steps=4,
        max_seq_len=2048,
        dropout=0.0,
    ).to(device)
    student_params = sum(p.numel() for p in student.parameters())
    print(f"  Student: {student_params:,} params")

    # Resume from checkpoint if specified
    start_step = 0
    if args.resume:
        print(f"Resuming from checkpoint: {args.resume}")
        ckpt = torch.load(args.resume, map_location=device)
        student.load_state_dict(ckpt["model_state_dict"])
        start_step = ckpt.get("step", 0)
        print(f"  Resumed at step {start_step}")
    
    # Data
    print("Loading TinyStories...")
    dataset = TinyStoriesStream(tokenizer, args.seq_len, args.max_stories)
    loader = DataLoader(dataset, batch_size=args.batch_size, collate_fn=collate_fn)
    data_iter = iter(loader)
    
    # Optimizer
    optimizer = torch.optim.AdamW(student.parameters(), lr=args.lr, weight_decay=0.01)
    
    # Training
    print(f"\nTraining for {args.steps} steps...")
    print(f"  batch_size={args.batch_size}, seq_len={args.seq_len}")
    print(f"  lr={args.lr}, temp={args.temp}")
    print(f"  Saves every {args.save_every} steps to {args.checkpoint_dir}/")
    
    step = start_step
    total_loss = 0
    total_kl = 0
    total_ce = 0
    log_interval = 100
    start_time = time.time()
    
    pbar = tqdm(total=args.steps, initial=start_step, desc="Distill")
    
    while step < args.steps:
        try:
            batch = next(data_iter)
        except StopIteration:
            data_iter = iter(loader)
            batch = next(data_iter)
        
        loss, kl_loss, ce_loss = train_step(
            student, teacher, batch, optimizer,
            temp=args.temp, device=device,
        )
        
        total_loss += loss
        total_kl += kl_loss
        total_ce += ce_loss
        step += 1
        pbar.update(1)
        
        if step % log_interval == 0:
            avg_loss = total_loss / log_interval
            avg_kl = total_kl / log_interval
            avg_ce = total_ce / log_interval
            elapsed = time.time() - start_time
            tok_per_sec = (log_interval * args.batch_size * args.seq_len) / elapsed if elapsed > 0 else 0
            pbar.set_postfix({
                "loss": f"{avg_loss:.4f}",
                "kl": f"{avg_kl:.4f}",
                "ce": f"{avg_ce:.4f}",
                "tok/s": f"{tok_per_sec:.0f}",
            })
            total_loss = 0
            total_kl = 0
            total_ce = 0
            start_time = time.time()
        
        if step % args.save_every == 0:
            ckpt_path = os.path.join(args.checkpoint_dir, f"distilled_step_{step:05d}.pt")
            torch.save({
                "step": step,
                "model_state_dict": student.state_dict(),
                "config": {
                    "vocab_size": vocab_size,
                    "d_model": args.d_model,
                    "n_heads": args.n_heads,
                    "d_ff": args.d_ff,
                    "n_layers": args.n_layers,
                    "max_steps": 4,
                    "max_seq_len": 2048,
                    "dropout": 0.0,
                },
                "loss": loss,
                "teacher": "gpt2",
                "tokenizer": "gpt2",
            }, ckpt_path)
            print(f"\n  Saved: {ckpt_path}")
    
    pbar.close()
    
    # Save final checkpoint
    final_path = os.path.join(args.checkpoint_dir, "distilled_final.pt")
    torch.save({
        "step": args.steps,
        "model_state_dict": student.state_dict(),
        "config": {
            "vocab_size": vocab_size,
            "d_model": args.d_model,
            "n_heads": args.n_heads,
            "d_ff": args.d_ff,
            "n_layers": args.n_layers,
            "max_steps": 4,
            "max_seq_len": 2048,
            "dropout": 0.0,
        },
        "loss": loss,
        "teacher": "gpt2",
        "tokenizer": "gpt2",
    }, final_path)
    print(f"\nDone! Final checkpoint: {final_path}")
    
    # Quick test
    print("\nTesting generation...")
    student.eval()
    prompt = "Once upon a time"
    prompt_ids = tokenizer.encode(prompt, return_tensors="pt").to(device)
    output, _ = student.generate(
        prompt_ids,
        max_new_tokens=30,
        temperature=0.8,
        top_k=40,
        repetition_penalty=1.1,
    )
    generated = tokenizer.decode(output[0].tolist(), skip_special_tokens=True)
    print(f"  Prompt: {prompt}")
    print(f"  Output: {generated}")


if __name__ == "__main__":
    main()
