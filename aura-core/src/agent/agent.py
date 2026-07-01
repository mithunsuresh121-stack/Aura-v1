from __future__ import annotations
"""
Cortex Agent — the agentic layer that gives the model identity, memory,
and tool-use capabilities.

Architecture:
  Identity (persistent task_emb) → hypernetwork → identity LoRA (always active)
  Knowledge Base retrieval → relevant prompt chunks → task embedding
  Conversation Memory → recent context → task embedding
  Tools → called when the model outputs tool calls

The agent composes multiple task embeddings into one, generating a single
LoRA that encodes identity + retrieved knowledge + conversation context.
"""
import json
import os
import re
import time
from pathlib import Path
from typing import Any

import torch
import torch.nn.functional as F
import numpy as np

from hypernetwork import apply_lora_to_model, clear_lora_from_model
from .identity import Identity
from .memory import ConversationMemory, FactMemory
from .tools import Tool, make_tools, format_tools_for_prompt
from .system_prompt import build_system_prompt


class Agent:
    """
    Agentic wrapper around the base model + hypernetwork.

    State:
      - identity: a learnable task_embedding (the "self" vector)
      - memory: conversation + fact memory
      - knowledge_base: loaded from prompt file ingestion
      - tools: list of available tools
    """

    def __init__(
        self,
        base_model: torch.nn.Module,
        hypernetwork: torch.nn.Module,
        lora_rank: int = 8,
        d_model: int = 768,
        device: str = "cpu",
        knowledge_base: dict | None = None,
        identity_path: str | None = None,
        memory_path: str = "memory.sqlite",
        tools: list[Tool] | None = None,
    ):
        self.base_model = base_model
        self.hypernetwork = hypernetwork
        self.lora_rank = lora_rank
        self.d_model = d_model
        self.device = device
        self.knowledge_base = knowledge_base or {"texts": [], "embeddings": np.zeros((0, d_model)), "sources": []}
        self.tools = tools or make_tools(knowledge_base)

        self.identity = Identity(d_model)
        if identity_path and Path(identity_path).exists():
            self.identity.load(identity_path, device)
        else:
            self.identity.to(device)

        self.conversation_memory = ConversationMemory(max_turns=20)
        self.fact_memory = FactMemory(memory_path)

        self._current_lora: list | None = None

    @torch.no_grad()
    def compose_task_embedding(
        self,
        user_message: str,
        n_retrieve: int = 3,
    ) -> torch.Tensor:
        """
        Compose a task embedding from:
          1. Identity vector (always active)
          2. Retrieved knowledge base chunks
          3. Recent conversation context
          4. The user's current message

        Returns a single [1, d_model] embedding.
        """
        emb = self.identity().to(self.device)  # [1, d_model]

        # Add retrieved knowledge
        if len(self.knowledge_base["embeddings"]) > 0:
            user_emb = self._embed_text(user_message)
            # cosine similarity
            sims = (user_emb @ self.knowledge_base["embeddings"].T).flatten() / (
                np.linalg.norm(user_emb) * np.linalg.norm(self.knowledge_base["embeddings"], axis=1)
            )
            top_idx = sims.argsort()[-n_retrieve:][::-1]
            for idx in top_idx:
                if sims[idx] > 0.3:  # relevance threshold
                    chunk_emb = torch.tensor(
                        self.knowledge_base["embeddings"][idx], device=self.device
                    ).unsqueeze(0)
                    emb = emb + chunk_emb * 0.3

        # Add conversation context
        context = self.conversation_memory.as_context(n=3)
        if context:
            ctx_emb = self._embed_text(context)
            emb = emb + ctx_emb.to(self.device) * 0.2

        emb = emb / emb.norm() * (self.d_model ** 0.5)
        return emb

    def _embed_text(self, text: str) -> np.ndarray:
        if not hasattr(self.base_model, 'tokenizer') or self.base_model.tokenizer is None:
            raise RuntimeError("Tokenizer not loaded — cannot embed text")
        ids = self.base_model.tokenizer.encode(text).ids[:256]
        tokens = torch.tensor([ids], device=self.device)
        with torch.no_grad():
            x = self.base_model.embedding(tokens) * (self.d_model ** 0.5)
            return x.mean(dim=1).cpu().numpy()

    @torch.no_grad()
    def generate_lora(self, task_emb: torch.Tensor):
        """Generate and apply LoRA from a composed task embedding."""
        clear_lora_from_model(self.base_model)

        loras = self.hypernetwork(task_emb)
        self._current_lora = [(A.cpu(), B.cpu()) for A, B in loras]

        loras_device = [(A.to(self.device), B.to(self.device)) for A, B in self._current_lora]
        apply_lora_to_model(self.base_model, loras_device, rank=self.lora_rank)

    def clear_lora(self):
        clear_lora_from_model(self.base_model)
        self._current_lora = None

    def generate(
        self,
        prompt: str,
        max_new_tokens: int = 256,
        temperature: float = 0.7,
        top_p: float = 1.0,
        auto_execute_tools: bool = False,
    ) -> tuple[str, float | None, list[dict]]:
        """Full generation pipeline: compose → LoRA → generate.
        Returns (text, loss, tool_suggestions).
        When auto_execute_tools=True, tools are automatically executed and
        continuations generated. When False, tool calls are returned as
        suggestions for user confirmation."""
        sys_prompt = build_system_prompt(self.tools)
        tool_prompt = sys_prompt + "\n\n" + prompt

        task_emb = self.compose_task_embedding(prompt)
        self.generate_lora(task_emb)

        if not hasattr(self.base_model, 'tokenizer') or self.base_model.tokenizer is None:
            raise RuntimeError("Tokenizer not loaded — cannot generate text")
        ids = self.base_model.tokenizer.encode(tool_prompt).ids
        prompt_tensor = torch.tensor([ids], device=self.device)

        gen_kwargs = dict(
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            top_k=int(top_p * 100) if top_p < 1.0 else 0,
        )

        output, gen_logits = self.base_model.generate(prompt_tensor, **gen_kwargs)
        generated_ids = output[0, prompt_tensor.shape[1]:].tolist()
        text = self.base_model.tokenizer.decode(generated_ids)

        # Compute loss on LoRA-augmented model from accumulated logits
        loss_val = None
        if gen_logits is not None and generated_ids:
            shift_logits = gen_logits[:, :len(generated_ids), :].contiguous()
            loss_val = F.cross_entropy(
                shift_logits.view(-1, shift_logits.shape[-1]),
                output[0, prompt_tensor.shape[1]:].view(-1),
            ).item()

        # Tool handling: suggest or auto-execute
        suggestions = self.parse_tool_suggestions(text)
        if suggestions and auto_execute_tools:
            text, _ = self._handle_tool_calls(text, max_new_tokens, temperature, top_p)
            suggestions = []

        self.conversation_memory.add("user", prompt)
        self.conversation_memory.add("assistant", text)

        self.clear_lora()
        return text, loss_val, suggestions

    def parse_tool_suggestions(self, text: str) -> list[dict]:
        """Parse tool call patterns from generated text WITHOUT executing.
        Pattern: [TOOL: tool_name(arg1, arg2)]
        Returns list of {name, args, display} dicts.
        """
        pattern = r'\[TOOL:\s*(\w+)\(([^)]*)\)\]'
        matches = re.findall(pattern, text)
        if not matches:
            return []

        suggestions = []
        for tool_name, args_str in matches:
            tool = next((t for t in self.tools if t.name == tool_name), None)
            args = [a.strip().strip('"\'') for a in args_str.split(',') if a.strip()]
            suggestions.append({
                "name": tool_name,
                "args": args,
                "display": f"{tool_name}({', '.join(args)})" if args else tool_name,
                "description": tool.description if tool else "unknown tool",
            })
        return suggestions

    def execute_tool_and_continue(
        self,
        tool_name: str,
        tool_args: list[str],
        context_text: str,
        max_new_tokens: int = 128,
        temperature: float = 0.7,
        top_p: float = 1.0,
    ) -> str:
        """Execute a single tool call and generate a continuation.
        Returns the full text (context + tool result + continuation).
        """
        tool = next((t for t in self.tools if t.name == tool_name), None)
        if tool is None:
            return context_text + f"\n[TOOL RESULT: unknown tool '{tool_name}']"

        result = tool.execute(*tool_args)
        full = context_text + f"\n[TOOL RESULT: {result}]"

        if not hasattr(self.base_model, 'tokenizer') or self.base_model.tokenizer is None:
            raise RuntimeError("Tokenizer not loaded")
        ids = self.base_model.tokenizer.encode(full).ids
        prompt_tensor = torch.tensor([ids], device=self.device)
        gen_kwargs = dict(
            max_new_tokens=max(16, max_new_tokens // 2),
            temperature=temperature,
            top_k=int(top_p * 100) if top_p < 1.0 else 0,
        )
        output, _ = self.base_model.generate(prompt_tensor, **gen_kwargs)
        generated_ids = output[0, prompt_tensor.shape[1]:].tolist()
        continuation = self.base_model.tokenizer.decode(generated_ids)
        return full + "\n" + continuation

    def _handle_tool_calls(
        self,
        text: str,
        max_new_tokens: int,
        temperature: float,
        top_p: float,
    ) -> tuple[str, bool]:
        """Legacy: auto-execute tool calls (used before suggest-then-wait flow).
        Kept for backward compatibility. Prefer parse_tool_suggestions() + execute_tool_and_continue()."""
        suggestions = self.parse_tool_suggestions(text)
        if not suggestions:
            return text, False

        pattern = r'\[TOOL:\s*(\w+)\(([^)]*)\)\]'
        clean_text = re.sub(pattern, '', text).strip()
        result_text = clean_text

        for s in suggestions:
            result_text = self.execute_tool_and_continue(
                s["name"], s["args"], result_text,
                max_new_tokens, temperature, top_p,
            )

        return result_text, True

    def save_identity(self, path: str):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.identity.save(path)

    def load_identity(self, path: str):
        self.identity.load(path, self.device)

    def get_state(self) -> dict:
        return {
            "identity_version": self.identity.version,
            "identity_norm": round(self.identity.embedding.norm().item(), 2),
            "conversation_turns": len(self.conversation_memory.turns),
            "facts_stored": len(self.fact_memory.all_facts()),
            "kb_chunks": len(self.knowledge_base.get("texts", [])),
            "tools_available": [t.name for t in self.tools],
        }
