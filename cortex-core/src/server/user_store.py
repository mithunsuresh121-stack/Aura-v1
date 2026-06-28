"""
User Store — manages per-user embeddings, LoRA weights, and conversation history.
Persistence on disk so users survive server restarts.
"""
import json
import time
import threading
from pathlib import Path
from typing import Optional, List, Tuple

import torch


class UserStore:
    def __init__(self, base_dir: str = "users"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _user_dir(self, user_id: str) -> Path:
        p = self.base_dir / user_id
        p.mkdir(parents=True, exist_ok=True)
        return p

    # --- Embeddings ---

    def get_embedding(self, user_id: str):
        path = self._user_dir(user_id) / "embedding.pt"
        if path.exists():
            return torch.load(path)
        return None

    def save_embedding(self, user_id: str, emb: torch.Tensor):
        with self._lock:
            torch.save(emb.detach().cpu(), self._user_dir(user_id) / "embedding.pt")

    # --- LoRA weights (saved after each improvement step) ---

    def save_lora(self, user_id: str, lora_weights: list):
        path = self._user_dir(user_id) / "lora.pt"
        cpu_weights = [(A.detach().cpu(), B.detach().cpu()) for A, B in lora_weights]
        with self._lock:
            torch.save(cpu_weights, path)

    def load_lora(self, user_id: str, device: str = "cpu"):
        path = self._user_dir(user_id) / "lora.pt"
        if not path.exists():
            return None
        cpu_weights = torch.load(path, map_location="cpu")
        return [(A.to(device), B.to(device)) for A, B in cpu_weights]

    def has_lora(self, user_id: str) -> bool:
        return (self._user_dir(user_id) / "lora.pt").exists()

    # --- Conversation history ---

    def add_conversation(self, user_id: str, prompt: str, completion: str):
        path = self._user_dir(user_id) / "conversations.jsonl"
        with self._lock:
            with open(path, "a") as f:
                f.write(json.dumps({
                    "prompt": prompt,
                    "completion": completion,
                    "timestamp": time.time(),
                }) + "\n")

    def get_recent_conversations(self, user_id: str, n: int = 20) -> list[dict]:
        path = self._user_dir(user_id) / "conversations.jsonl"
        if not path.exists():
            return []
        with open(path) as f:
            lines = f.readlines()
        recent = [json.loads(l) for l in lines if l.strip()][-n:]
        return recent

    def clear_user(self, user_id: str):
        import shutil
        path = self._user_dir(user_id)
        with self._lock:
            shutil.rmtree(path)

    def list_users(self) -> list[str]:
        return sorted([d.name for d in self.base_dir.iterdir() if d.is_dir()])

    @staticmethod
    def compute_embedding_from_history(
        conversations: list[dict],
        model,
        tokenizer,
        device: str = "cpu",
    ) -> torch.Tensor:
        """Average the model's own embeddings over recent user text."""
        all_text = " ".join(
            f"User: {c['prompt']} Assistant: {c['completion']}"
            for c in conversations[-10:]
        )
        if not all_text.strip():
            all_text = "User: Hello Assistant: Hi"
        ids = tokenizer.encode(all_text).ids
        if not ids:
            ids = [0]
        token_tensor = torch.tensor([ids[:512]], device=device)
        with torch.no_grad():
            emb = model.embedding(token_tensor).mean(dim=1)
        return emb / emb.norm(dim=-1, keepdim=True)

    @staticmethod
    def train_lora_on_user_data(
        model,
        tokenizer,
        conversations: list[dict],
        lora_rank: int = 8,
        lr: float = 3e-4,
        steps: int = 20,
        device: str = "cpu",
        init_loras: Optional[list] = None,
    ) -> list[tuple[torch.Tensor, torch.Tensor]]:
        """Fine-tune LoRA weights directly on a user's conversation history.
        
        Bypasses the HyperNetwork bottleneck — each user gets their own
        dedicated LoRA, trained on their actual conversations.
        Returns list of (A, B) tuples, one per attention projection.
        """
        from hypernetwork import apply_lora_to_model, clear_lora_from_model, LoraLinear

        if not conversations:
            return init_loras or []

        vocab_size = model.output.weight.shape[0]
        n_modules = model.n_layers * 4
        d_model = model.d_model

        model.eval()
        for p in model.parameters():
            p.requires_grad_(False)

        # Init LoRA weights (random if no init provided)
        if init_loras:
            loras = [(A.clone().to(device), B.clone().to(device)) for A, B in init_loras]
        else:
            loras = [
                (torch.randn(d_model, lora_rank, device=device) * 0.01,
                 torch.randn(lora_rank, d_model, device=device) * 0.01)
                for _ in range(n_modules)
            ]

        # Wrap in nn.Parameter so they're trainable
        lora_params = [
            (torch.nn.Parameter(A), torch.nn.Parameter(B))
            for A, B in loras
        ]

        optimizer = torch.optim.AdamW(
            [p for pair in lora_params for p in pair],
            lr=lr, weight_decay=0.01,
        )

        # Prepare training examples from conversations
        examples = []
        for c in conversations[-50:]:
            text = f"User: {c['prompt']}\nAssistant: {c['completion']}"
            ids = tokenizer.encode(text).ids
            if len(ids) < 10 or len(ids) > 512:
                continue
            # Find the Assistant: boundary
            all_ids = torch.tensor([ids], device=device)
            # Simple split: first 80% as prompt, last 20% as target
            split = int(len(ids) * 0.8)
            prompt_ids = all_ids[:, :split]
            target_ids = all_ids[:, split:]
            if target_ids.shape[1] < 2:
                continue
            examples.append((prompt_ids, target_ids))

        if len(examples) < 2:
            return [(A.detach().cpu(), B.detach().cpu()) for A, B in loras]

        # Training loop
        targets = ["wq", "wk", "wv", "wo"]
        for step in range(steps):
            total_loss = 0.0
            for prompt_ids, target_ids in examples:
                optimizer.zero_grad()

                # Apply current LoRA to all attention projections
                idx = 0
                for block in model.blocks:
                    for target in targets:
                        orig = getattr(block.attention, target)
                        A, B = lora_params[idx]
                        if not isinstance(orig, LoraLinear):
                            lora_lin = LoraLinear(orig, lora_rank)
                            lora_lin.set_lora(A, B)
                            setattr(block.attention, target, lora_lin)
                        else:
                            orig.set_lora(A, B)
                        idx += 1

                all_ids = torch.cat([prompt_ids, target_ids], dim=1)
                logits, _, _ = model(all_ids)
                shift_logits = logits[:, prompt_ids.shape[1] - 1:-1, :].contiguous()
                loss = torch.nn.functional.cross_entropy(
                    shift_logits.view(-1, vocab_size),
                    target_ids.view(-1),
                )
                loss.backward()
                total_loss += loss.item()

            torch.nn.utils.clip_grad_norm_(
                [p for pair in lora_params for p in pair], 1.0,
            )
            optimizer.step()

        clear_lora_from_model(model)

        return [(A.detach().cpu(), B.detach().cpu()) for A, B in lora_params]
