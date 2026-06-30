from __future__ import annotations
"""
Hypernetwork — generates LoRA adapters from task embeddings.
- Input: task embedding vector (d_model-dim)
- Output: LoRA A/B matrices for each target module in the dense core
"""
import torch
import torch.nn as nn
import torch.nn.functional as F
import math


class SwiGLU(nn.Module):
    def __init__(self, dim: int, hidden: int):
        super().__init__()
        self.w1 = nn.Linear(dim, hidden, bias=False)
        self.w2 = nn.Linear(hidden, dim, bias=False)
        self.w3 = nn.Linear(dim, hidden, bias=False)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.w2(F.silu(self.w1(x)) * self.w3(x))


class HyperNetwork(nn.Module):
    """
    Maps task embeddings to LoRA adapter weights.

    Architecture:
        task_emb → MLP → bottleneck z
        For each module: concat(z, module_embedding) → LoRA_A, LoRA_B

    The LoRA generators are shared across all modules, differentiated
    by learned per-module embeddings.
    """
    def __init__(
        self,
        d_model: int = 768,
        bottleneck: int = 256,
        lora_rank: int = 8,
        n_layers: int = 6,
        targets_per_layer: int = 4,  # Q, K, V, O
    ):
        super().__init__()
        self.d_model = d_model
        self.lora_rank = lora_rank
        self.n_modules = n_layers * targets_per_layer

        # Task encoder: d_model → bottleneck
        self.encoder = nn.Sequential(
            nn.Linear(d_model, bottleneck * 2, bias=False),
            nn.LayerNorm(bottleneck * 2),
            SwiGLU(bottleneck * 2, bottleneck * 4),
            nn.Linear(bottleneck * 2, bottleneck, bias=False),
            nn.LayerNorm(bottleneck),
        )

        # Per-module learned embeddings
        self.module_emb = nn.Embedding(self.n_modules, bottleneck)

        # Shared LoRA generator (conditioned on task + module embedding)
        gen_input_dim = bottleneck * 2  # task_bottleneck + module_emb
        self.gen_A = nn.Linear(gen_input_dim, d_model * lora_rank, bias=False)
        self.gen_B = nn.Linear(gen_input_dim, lora_rank * d_model, bias=False)

        self._init_params()

    def _init_params(self):
        for p in self.parameters():
            if p.dim() > 1:
                nn.init.xavier_uniform_(p, gain=0.1)

    def forward(
        self,
        task_emb: torch.Tensor,
    ) -> list[tuple[torch.Tensor, torch.Tensor]]:
        """
        Args:
            task_emb: [batch, d_model] task embedding
        Returns:
            List of (A, B) tuples for each module, each shape:
              A: [d_model, lora_rank], B: [lora_rank, d_model]
        """
        batch_size = task_emb.shape[0]
        z = self.encoder(task_emb)  # [batch, bottleneck]

        loras = []
        for module_id in range(self.n_modules):
            mod_id_tensor = torch.full((batch_size,), module_id, device=task_emb.device, dtype=torch.long)
            mod_emb = self.module_emb(mod_id_tensor)  # [batch, bottleneck]

            combined = torch.cat([z, mod_emb], dim=-1)  # [batch, bottleneck * 2]

            A_raw = self.gen_A(combined)
            B_raw = self.gen_B(combined)

            A = A_raw.view(batch_size, self.d_model, self.lora_rank)
            B = B_raw.view(batch_size, self.lora_rank, self.d_model)

            loras.append((A, B))

        return loras

    def get_module_mapping(self) -> list[str]:
        """Return human-readable names for each module index."""
        names = []
        targets = ["q", "k", "v", "o"]
        for layer in range(6):
            for target in targets:
                names.append(f"layer_{layer}.{target}")
        return names


class LoraLinear(nn.Module):
    """Wraps a Linear layer with a LoRA adapter that can be applied externally."""
    def __init__(self, original: nn.Linear, rank: int = 8):
        super().__init__()
        self.original = original
        self.rank = rank
        self.register_buffer('lora_A', None)
        self.register_buffer('lora_B', None)
        self.scaling = 1.0 / rank

    def set_lora(self, A: torch.Tensor, B: torch.Tensor):
        self.lora_A = A
        self.lora_B = B

    def clear_lora(self):
        self.lora_A = None
        self.lora_B = None

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out = self.original(x)
        if self.lora_A is not None and self.lora_B is not None:
            if self.lora_A.dim() == 3:
                B_t = self.lora_B.transpose(1, 2)
                A_t = self.lora_A.transpose(1, 2)
                lora_update = torch.bmm(x, B_t)
                lora_update = torch.bmm(lora_update, A_t)
            else:
                lora_update = (x @ self.lora_B.t()) @ self.lora_A.t()
            out = out + lora_update * self.scaling
        return out


def apply_lora_to_model(
    model: "UniversalDenseCore",
    lora_weights: list[tuple[torch.Tensor, torch.Tensor]],
    rank: int = 8,
):
    """
    Apply LoRA adapters to the model's attention projections.
    Replaces the Linear layers with LoraLinear wrappers.
    """
    layer_idx = 0
    targets = ["wq", "wk", "wv", "wo"]

    for block in model.blocks:
        for target in targets:
            orig_linear = getattr(block.attention, target)
            lora_linear = LoraLinear(orig_linear, rank)
            A, B = lora_weights[layer_idx]
            if A.shape[0] == 1:
                A, B = A.squeeze(0), B.squeeze(0)
            lora_linear.set_lora(A, B)
            setattr(block.attention, target, lora_linear)
            layer_idx += 1


def clear_lora_from_model(model: "UniversalDenseCore"):
    """Remove LoRA adapters, restoring original Linear layers."""
    targets = ["wq", "wk", "wv", "wo"]
    for block in model.blocks:
        for target in targets:
            current = getattr(block.attention, target)
            if isinstance(current, LoraLinear):
                setattr(block.attention, target, current.original)


def task_text_to_embedding(
    text: str,
    tokenizer,
    embed_model: nn.Module | None = None,
    device: str = "cpu",
) -> torch.Tensor:
    """
    Convert a task description to an embedding.
    Uses the model's embedding layer if no embed_model is provided.
    """
    if embed_model is not None:
        tokens = tokenizer.encode(text).ids
        token_tensor = torch.tensor([tokens], device=device)
        with torch.no_grad():
            emb = embed_model(token_tensor).mean(dim=1)
        return emb
    else:
        tokens = tokenizer.encode(text).ids[:64]
        token_tensor = torch.tensor([tokens], device=device)
        with torch.no_grad():
            emb = embed_model.embedding(token_tensor).mean(dim=1)
        return emb


if __name__ == "__main__":
    hn = HyperNetwork(d_model=768, lora_rank=8)
    total = sum(p.numel() for p in hn.parameters())
    print(f"HyperNetwork params: {total:,}")

    test_emb = torch.randn(1, 768)
    loras = hn(test_emb)
    print(f"Generated {len(loras)} LoRA modules")
    A, B = loras[0]
    print(f"  Module 0 A: {A.shape}, B: {B.shape}")
    print(f"  Total LoRA params per task: {sum(A.numel() + B.numel() for A, B in loras):,}")
    print(f"  Module names: {hn.get_module_mapping()[:4]}...")
