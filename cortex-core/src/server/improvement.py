from __future__ import annotations
"""
Self-Improvement Engine — online learning loop for the hypernetwork.

Collects real inference data, identifies tasks where the LoRA-augmented model
had high uncertainty (self-loss), and fine-tunes the hypernetwork to generate
better adapters. The model literally learns from its own mistakes at runtime.
"""
import random
import time
import threading
from pathlib import Path

import torch
import torch.nn.functional as F
from torch import optim


class SelfImprovementEngine:
    """
    Online meta-learning: served requests generate training data, hypernetwork
    improves from its own failures.

    Strategy:
      - Keep a buffer of the hardest examples (highest self-loss after generation)
      - Periodically sample a batch and fine-tune the hypernetwork
      - Training signal: minimize loss on the model's own completions
    """

    def __init__(
        self,
        hypernetwork: torch.nn.Module,
        base_model: torch.nn.Module,
        lora_rank: int = 8,
        max_buffer: int = 128,
        batch_size: int = 4,
        min_for_train: int = 16,
        lr: float = 5e-6,
        device: str = "cpu",
        checkpoint_dir: str | None = None,
    ):
        self.hypernetwork = hypernetwork
        self.base_model = base_model
        self.lora_rank = lora_rank
        self.device = device
        self.checkpoint_dir = checkpoint_dir

        self.buffer: list = []
        self.max_buffer = max_buffer
        self.batch_size = batch_size
        self.min_for_train = min_for_train

        self.optimizer = optim.AdamW(hypernetwork.parameters(), lr=lr, weight_decay=0.01)
        self.steps = 0
        self.examples_collected = 0
        self.total_train_loss = 0.0
        self.lock = threading.Lock()

        self._freeze_base_model()

    def _freeze_base_model(self):
        for p in self.base_model.parameters():
            p.requires_grad_(False)

    def collect(
        self,
        task_emb: torch.Tensor,
        prompt_ids: torch.Tensor,
        completion_ids: torch.Tensor,
        loss: float,
    ):
        """Store a (task, prompt, completion, loss) example.

        Only keeps the hardest examples (highest loss) — these are the
        tasks where the LoRA failed most, so they provide the strongest
        training signal.
        """
        with self.lock:
            self.buffer.append((
                task_emb.detach().cpu(),
                prompt_ids.detach().cpu(),
                completion_ids.detach().cpu(),
                loss,
            ))
            self.examples_collected += 1

            if len(self.buffer) > self.max_buffer:
                self.buffer.sort(key=lambda x: x[3], reverse=True)
                self.buffer = self.buffer[:self.max_buffer]

    @property
    def ready(self) -> bool:
        return len(self.buffer) >= self.min_for_train

    def step(self) -> float | None:
        """One improvement step: sample hardest batch → forward → backprop.

        Returns average loss for the batch, or None if buffer isn't ready.
        """
        if not self.ready:
            return None

        with self.lock:
            self.buffer.sort(key=lambda x: x[3], reverse=True)
            # Sample from the top half (hardest)
            pool = self.buffer[:max(len(self.buffer) // 2, self.batch_size)]
            batch = random.sample(pool, min(self.batch_size, len(pool)))

        from hypernetwork import apply_lora_to_model, clear_lora_from_model

        self.hypernetwork.train()
        self.optimizer.zero_grad()

        total_loss = 0.0
        vocab_size = self.base_model.output.weight.shape[0]

        for task_emb, prompt_ids, completion_ids, _ in batch:
            task_emb = task_emb.to(self.device)
            prompt_ids = prompt_ids.to(self.device)
            completion_ids = completion_ids.to(self.device)

            # Generate fresh LoRA from current hypernetwork
            loras_raw = self.hypernetwork(task_emb)  # list of (A, B), grad flows
            apply_lora_to_model(self.base_model, loras_raw, rank=self.lora_rank)

            # Forward on prompt + completion
            all_ids = torch.cat([prompt_ids, completion_ids], dim=1)
            logits, info, _ = self.base_model.forward(all_ids)

            # Shift so we predict completion tokens
            shift_logits = logits[:, prompt_ids.shape[1] - 1:-1, :].contiguous()
            loss = F.cross_entropy(
                shift_logits.view(-1, vocab_size),
                completion_ids.view(-1),
            )
            total_loss = total_loss + loss

            clear_lora_from_model(self.base_model)

        total_loss = total_loss / len(batch)
        total_loss.backward()

        torch.nn.utils.clip_grad_norm_(self.hypernetwork.parameters(), 1.0)
        self.optimizer.step()

        self.steps += 1
        self.total_train_loss += total_loss.item()

        self.hypernetwork.eval()
        return total_loss.item()

    def save_checkpoint(self, path: str):
        torch.save({
            "step": self.steps,
            "hypernet_state_dict": self.hypernetwork.state_dict(),
            "optimizer_state_dict": self.optimizer.state_dict(),
            "avg_loss": self.total_train_loss / max(self.steps, 1),
            "examples_collected": self.examples_collected,
        }, path)

    def stats(self) -> dict:
        return {
            "buffer_size": len(self.buffer),
            "examples_collected": self.examples_collected,
            "improvement_steps": self.steps,
            "avg_train_loss": round(self.total_train_loss / max(self.steps, 1), 4),
            "ready": self.ready,
        }
