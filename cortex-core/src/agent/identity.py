"""
Persistent identity for the agent.

The identity is a vector (task embedding) that represents the model's "self" —
its personality, goals, and behavioral defaults. This vector evolves over time
through the self-improvement engine, creating a unique, learned identity.

Architecture:
  identity_emb (torch.Tensor, [d_model]) — persistent across restarts
  updated by: self-improvement engine (gradient on self-loss)
  consumed by: hypernetwork → generates the "identity LoRA" always active
"""
import json
import os
from pathlib import Path

import torch
import torch.nn as nn
import torch.nn.functional as F


def init_identity_embedding(d_model: int = 768, seed: str = "cortex") -> torch.Tensor:
    """Create a deterministic initial identity from a seed string."""
    rng = torch.Generator()
    rng.manual_seed(sum(ord(c) for c in seed))
    emb = torch.randn(d_model, generator=rng) * 0.02
    emb = emb / emb.norm() * (d_model ** 0.5)
    return emb


class Identity(nn.Module):
    """
    A learnable task_embedding that represents the model's identity.

    The identity vector is fed to the hypernetwork to generate a persistent
    "identity LoRA" — task-specific weights that shape all outputs.

    It evolves via the self-improvement engine: each improvement step
    updates the identity vector via gradient descent on self-loss.
    """

    def __init__(self, d_model: int = 768):
        super().__init__()
        self.d_model = d_model
        self.embedding = nn.Parameter(init_identity_embedding(d_model))
        self.version = 0

    @torch.no_grad()
    def normalize(self):
        self.embedding.data = self.embedding.data / self.embedding.data.norm() * (self.d_model ** 0.5)

    def forward(self) -> torch.Tensor:
        return self.embedding.unsqueeze(0)  # [1, d_model]

    def state_dict(self) -> dict:
        return {
            "embedding": self.embedding.detach().cpu(),
            "version": self.version,
        }

    def load_state_dict(self, state: dict):
        self.embedding.data = state["embedding"].to(self.embedding.device)
        self.version = state.get("version", 0)

    def save(self, path: str):
        torch.save(self.state_dict(), path)

    def load(self, path: str, device: str = "cpu"):
        state = torch.load(path, map_location=device)
        self.load_state_dict(state)
        self.to(device)

    def __repr__(self):
        return f"Identity(d_model={self.d_model}, version={self.version}, norm={self.embedding.norm().item():.2f})"
