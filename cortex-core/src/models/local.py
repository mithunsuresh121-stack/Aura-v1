from typing import AsyncGenerator, Optional
import torch
from .base import ModelBackend


class LocalBackend(ModelBackend):
    name = "local"

    def __init__(self, model, tokenizer, device: str = "cpu"):
        self.model = model
        self.tokenizer = tokenizer
        self.device = device

    async def generate(
        self,
        messages: list[dict],
        max_tokens: int = 256,
        temperature: float = 0.7,
        top_p: float = 1.0,
        stop: Optional[list[str]] = None,
    ) -> str:
        prompt = self._fmt_messages(messages)
        ids = self.tokenizer.encode(prompt).ids
        prompt_tensor = torch.tensor([ids], device=self.device)
        with torch.no_grad():
            output_ids, _ = self.model.generate(
                prompt_tensor,
                max_new_tokens=max_tokens,
                temperature=temperature,
                top_k=int(top_p * 100) if top_p < 1.0 else 50,
            )
        gen_ids = output_ids[0, prompt_tensor.shape[1]:].tolist()
        return self.tokenizer.decode(gen_ids)

    async def generate_stream(
        self,
        messages: list[dict],
        max_tokens: int = 256,
        temperature: float = 0.7,
        top_p: float = 1.0,
        stop: Optional[list[str]] = None,
    ) -> AsyncGenerator[str, None]:
        prompt = self._fmt_messages(messages)
        ids = self.tokenizer.encode(prompt).ids
        prompt_tensor = torch.tensor([ids], device=self.device)
        x = prompt_tensor
        past_kv = None
        for _ in range(max_tokens):
            with torch.no_grad():
                logits, _, past_kv = self.model.forward(x, past_key_values=past_kv, use_cache=True)
            logits = logits[:, -1, :] / temperature
            probs = torch.softmax(logits, dim=-1)
            next_token = torch.multinomial(probs, num_samples=1)
            token_text = self.tokenizer.decode([next_token.item()])
            yield token_text
            x = next_token
            if stop and token_text.strip() in stop:
                break

    async def health(self) -> dict:
        return {
            "status": "ok",
            "model": "local",
            "params": sum(p.numel() for p in self.model.parameters()),
        }

    def _fmt_messages(self, messages: list[dict]) -> str:
        parts = []
        for msg in messages:
            if msg["role"] == "system":
                parts.append(f"System: {msg['content']}")
            elif msg["role"] == "user":
                parts.append(f"User: {msg['content']}")
            elif msg["role"] == "assistant":
                parts.append(f"Assistant: {msg['content']}")
        parts.append("Assistant:")
        return "\n".join(parts)
