from __future__ import annotations
import torch
import torch.nn as nn
import torch.nn.functional as F
import math


class RMSNorm(nn.Module):
    def __init__(self, dim: int, eps: float = 1e-6):
        super().__init__()
        self.eps = eps
        self.weight = nn.Parameter(torch.ones(dim))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        rms = torch.sqrt(x.pow(2).mean(-1, keepdim=True) + self.eps)
        return x / rms * self.weight


class RotaryEmbedding(nn.Module):
    def __init__(self, dim: int, max_seq_len: int = 2048):
        super().__init__()
        inv_freq = 1.0 / (10000 ** (torch.arange(0, dim, 2).float() / dim))
        self.register_buffer("inv_freq", inv_freq)
        pos = torch.arange(max_seq_len, dtype=torch.float)
        freqs = torch.einsum("i,j->ij", pos, inv_freq)
        self.register_buffer("cos", freqs.cos())
        self.register_buffer("sin", freqs.sin())

    def forward(self, x: torch.Tensor, start_pos: int = 0):
        seq_len = x.shape[1]
        cos = self.cos[start_pos:start_pos + seq_len].unsqueeze(0).unsqueeze(0)
        sin = self.sin[start_pos:start_pos + seq_len].unsqueeze(0).unsqueeze(0)
        return cos, sin


def rotate_half(x: torch.Tensor) -> torch.Tensor:
    x1, x2 = x.chunk(2, dim=-1)
    return torch.cat((-x2, x1), dim=-1)


def apply_rotary(x: torch.Tensor, cos: torch.Tensor, sin: torch.Tensor) -> torch.Tensor:
    return (x * cos) + (rotate_half(x) * sin)


class MultiHeadAttention(nn.Module):
    def __init__(self, d_model: int, n_heads: int, dropout: float = 0.0):
        super().__init__()
        assert d_model % n_heads == 0
        self.d_model = d_model
        self.n_heads = n_heads
        self.head_dim = d_model // n_heads
        self.wq = nn.Linear(d_model, d_model, bias=False)
        self.wk = nn.Linear(d_model, d_model, bias=False)
        self.wv = nn.Linear(d_model, d_model, bias=False)
        self.wo = nn.Linear(d_model, d_model, bias=False)
        self.dropout = nn.Dropout(dropout)

    def forward(
        self,
        x: torch.Tensor,
        cos: torch.Tensor,
        sin: torch.Tensor,
        mask: torch.Tensor | None = None,
        past_kv: tuple[torch.Tensor, torch.Tensor] | None = None,
    ) -> tuple[torch.Tensor, tuple[torch.Tensor, torch.Tensor]]:
        B, T, _ = x.shape
        q = self.wq(x).view(B, T, self.n_heads, self.head_dim).transpose(1, 2)
        k = self.wk(x).view(B, T, self.n_heads, self.head_dim).transpose(1, 2)
        v = self.wv(x).view(B, T, self.n_heads, self.head_dim).transpose(1, 2)

        q = apply_rotary(q, cos, sin)
        k = apply_rotary(k, cos, sin)

        if past_kv is not None:
            k_prev, v_prev = past_kv
            k = torch.cat([k_prev, k], dim=2)
            v = torch.cat([v_prev, v], dim=2)

        attn = torch.matmul(q, k.transpose(-2, -1)) / math.sqrt(self.head_dim)
        if mask is not None:
            attn = attn.masked_fill(mask == 0, float("-inf"))
        attn = F.softmax(attn, dim=-1)
        attn = self.dropout(attn)

        out = torch.matmul(attn, v).transpose(1, 2).contiguous().view(B, T, self.d_model)
        return self.wo(out), (k, v)


class SwiGLUFFN(nn.Module):
    def __init__(self, d_model: int, d_ff: int, dropout: float = 0.0):
        super().__init__()
        self.w1 = nn.Linear(d_model, d_ff, bias=False)
        self.w2 = nn.Linear(d_ff, d_model, bias=False)
        self.w3 = nn.Linear(d_model, d_ff, bias=False)
        self.dropout = nn.Dropout(dropout)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.w2(self.dropout(F.silu(self.w1(x)) * self.w3(x)))


class TransitionBlock(nn.Module):
    def __init__(self, d_model: int, n_heads: int, d_ff: int, dropout: float = 0.0):
        super().__init__()
        self.attention = MultiHeadAttention(d_model, n_heads, dropout)
        self.ffn = SwiGLUFFN(d_model, d_ff, dropout)
        self.norm1 = RMSNorm(d_model)
        self.norm2 = RMSNorm(d_model)
        self.dropout = nn.Dropout(dropout)

    def forward(
        self,
        x: torch.Tensor,
        cos: torch.Tensor,
        sin: torch.Tensor,
        mask: torch.Tensor | None = None,
        past_kv: tuple[torch.Tensor, torch.Tensor] | None = None,
    ) -> tuple[torch.Tensor, tuple[torch.Tensor, torch.Tensor]]:
        attn_out, kv = self.attention(self.norm1(x), cos, sin, mask, past_kv)
        x = x + self.dropout(attn_out)
        x = x + self.dropout(self.ffn(self.norm2(x)))
        return x, kv


class HaltingUnit(nn.Module):
    def __init__(self, d_model: int):
        super().__init__()
        self.gate = nn.Linear(d_model, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return torch.sigmoid(self.gate(x))


class UniversalDenseCore(nn.Module):
    def __init__(
        self,
        vocab_size: int = 16384,
        d_model: int = 768,
        n_heads: int = 12,
        d_ff: int = 2048,
        n_layers: int = 6,
        max_steps: int = 4,
        halting_epsilon: float = 0.01,
        max_seq_len: int = 2048,
        dropout: float = 0.0,
    ):
        super().__init__()
        self.d_model = d_model
        self.max_steps = max_steps
        self.halting_epsilon = halting_epsilon
        self.max_seq_len = max_seq_len
        self.n_layers = n_layers

        self.embedding = nn.Embedding(vocab_size, d_model)
        self.rotary = RotaryEmbedding(d_model // n_heads * 2, max_seq_len)
        self.dropout = nn.Dropout(dropout)

        self.blocks = nn.ModuleList([
            TransitionBlock(d_model, n_heads, d_ff, dropout)
            for _ in range(n_layers)
        ])

        self.halting_units = nn.ModuleList([
            HaltingUnit(d_model) for _ in range(n_layers)
        ])

        self.norm_out = RMSNorm(d_model)
        self.output = nn.Linear(d_model, vocab_size, bias=False)
        self.output.weight = self.embedding.weight

        self._init_params()

    def _init_params(self):
        for p in self.parameters():
            if p.dim() > 1:
                nn.init.xavier_uniform_(p, gain=0.02)

    def quantize(self, mode: str = "fp16"):
        """Reduce model precision to save memory.
        Modes: 'none' (float32), 'fp16' (half), 'int8' (dynamic quantization).
        Call before eval() for inference. Only Linear layers are quantized;
        embeddings, norms, and halting gates remain in float32 for stability.
        """
        if mode == "fp16":
            self.half()
        elif mode == "int8":
            self.to(torch.float32)
            torch.quantization.quantize_dynamic(
                self, {nn.Linear}, dtype=torch.qint8, inplace=True
            )
        elif mode == "none" or mode == "fp32":
            self.to(torch.float32)
            if hasattr(self, "embedding"):
                self.embedding = self.embedding.float()
        return self

    def forward(
        self,
        input_ids: torch.Tensor,
        past_key_values: list[tuple[torch.Tensor, torch.Tensor]] | None = None,
        use_cache: bool = False,
    ) -> tuple[torch.Tensor, dict]:
        B, T = input_ids.shape
        device = input_ids.device

        start_pos = 0
        if past_key_values is not None:
            start_pos = past_key_values[0][0].shape[2]

        x = self.embedding(input_ids) * math.sqrt(self.d_model)
        cos, sin = self.rotary(x, start_pos)

        total_updates = torch.zeros(B, T, device=device)
        new_past_key_values = [] if use_cache else None

        for layer_idx, (block, halting_unit) in enumerate(zip(self.blocks, self.halting_units)):
            layer_kv = past_key_values[layer_idx] if past_key_values is not None and layer_idx < len(past_key_values) else None

            if T > 1:
                h = x
                halting_scores = torch.zeros(B, T, device=device)
                layer_updates = torch.zeros(B, T, device=device)
                layer_out = torch.zeros_like(x)
                active = torch.ones(B, T, dtype=torch.bool, device=device)

                for step in range(self.max_steps):
                    cur_kv = layer_kv if step == 0 else None
                    mask = None
                    if step == 0 and layer_kv is None:
                        causal_mask = torch.triu(torch.full((T, T), float("-inf"), device=device), diagonal=1)
                        mask = causal_mask.unsqueeze(0).unsqueeze(0).expand(B, 1, T, T)
                        mask = (mask == 0)

                    h_step, new_kv = block(h, cos, sin, mask, cur_kv)

                    h_prob = halting_unit(h_step).squeeze(-1)
                    new_scores = halting_scores + h_prob
                    halt = (new_scores >= (1.0 - self.halting_epsilon)) & active

                    if halt.any():
                        layer_out = torch.where(halt.unsqueeze(-1), h_step, layer_out)
                        layer_updates = torch.where(halt, torch.full_like(layer_updates, step + 1), layer_updates)
                        active = active & ~halt

                    halting_scores = torch.where(active, new_scores, halting_scores)
                    still_active = active & ~halt
                    layer_out = torch.where(still_active.unsqueeze(-1), h_step, layer_out)

                    if not active.any():
                        break
                    h = h_step

                if active.any():
                    h_step, _ = block(h, cos, sin, None)
                    layer_out = torch.where(active.unsqueeze(-1), h_step, layer_out)
                    layer_updates = torch.where(active, torch.full_like(layer_updates, self.max_steps), layer_updates)

                total_updates = total_updates + layer_updates
                x = layer_out

                if use_cache:
                    new_past_key_values.append(new_kv)
            else:
                mask = None
                start_pos_local = 0
                if layer_kv is not None:
                    start_pos_local = layer_kv[0].shape[2]
                    cos_local, sin_local = self.rotary(x, start_pos_local)
                else:
                    cos_local, sin_local = cos, sin

                h = x
                for step in range(self.max_steps):
                    cur_kv = layer_kv if step == 0 else None
                    h, step_kv = block(h, cos_local, sin_local, mask, cur_kv)
                    h_prob = halting_unit(h).squeeze(-1)
                    if (h_prob >= (1.0 - self.halting_epsilon)).any():
                        break

                x = h
                if use_cache:
                    new_past_key_values.append(step_kv)

        x = self.norm_out(x)
        logits = self.output(x)

        info = {
            "n_updates": total_updates if T > 1 else torch.zeros(B, 1),
            "ponder_cost": total_updates if T > 1 else torch.zeros(B, 1),
        }

        return logits, info, new_past_key_values

    def compute_loss(
        self,
        logits: torch.Tensor,
        targets: torch.Tensor,
        info: dict | None = None,
        beta: float = 0.01,
    ) -> torch.Tensor:
        B, T, V = logits.shape
        loss = F.cross_entropy(logits.view(-1, V), targets.view(-1))

        if info is not None:
            ponder_cost = info["ponder_cost"]
            beta_loss = beta * ponder_cost.mean()

        return loss + beta_loss if info is not None else loss

    @torch.no_grad()
    def generate(
        self,
        prompt: torch.Tensor,
        max_new_tokens: int = 64,
        temperature: float = 0.8,
        top_k: int = 40,
        repetition_penalty: float = 1.0,
        timeout_seconds: float = 0.0,
    ) -> tuple[torch.Tensor, torch.Tensor | None]:
        """
        Returns (output_ids, generated_logits).
        generated_logits is [1, max_new_tokens, vocab_size] or None.
        If timeout_seconds > 0, generation stops early if it exceeds the limit.
        """
        import time as _time
        self.eval()
        device = next(self.parameters()).device
        x = prompt.to(device)
        t_start = _time.monotonic()

        gen_logits = []

        if max_new_tokens <= 0:
            return x, None

        logits, _, past_kv = self.forward(x, use_cache=True)
        logits = logits[:, -1, :] / temperature
        if repetition_penalty != 1.0:
            for token_id in x[0].tolist():
                logits[:, token_id] /= repetition_penalty
        probs = torch.softmax(logits, dim=-1)
        next_token = torch.multinomial(probs, num_samples=1)
        gen_logits.append(logits)
        x = torch.cat([x, next_token], dim=-1)

        for _ in range(max_new_tokens - 1):
            if timeout_seconds > 0 and _time.monotonic() - t_start > timeout_seconds:
                break
            logits, _, past_kv = self.forward(next_token, past_key_values=past_kv, use_cache=True)
            logits = logits[:, -1, :] / temperature

            if repetition_penalty != 1.0:
                for token_id in x[0].tolist():
                    logits[:, token_id] /= repetition_penalty

            if top_k > 0:
                values, _ = torch.topk(logits, top_k, dim=-1)
                logits[logits < values[:, -1:]] = float("-inf")

            probs = torch.softmax(logits, dim=-1)
            next_token = torch.multinomial(probs, num_samples=1)
            gen_logits.append(logits)
            x = torch.cat([x, next_token], dim=-1)

        all_logits = torch.stack(gen_logits, dim=1) if gen_logits else None
        return x, all_logits
