"""
SubAgent — a single delegate agent with its own context, model, and tools.
Each sub-agent runs independently and reports back to the orchestrator.
"""
import json
import asyncio
import logging
from typing import Any, Optional
from dataclasses import dataclass, field

logger = logging.getLogger("cortex.orchestration")


@dataclass
class SubAgentResult:
    agent_id: str
    task: str
    output: str
    status: str = "completed"
    error: Optional[str] = None
    metadata: dict = field(default_factory=dict)


class SubAgent:
    def __init__(
        self,
        agent_id: str,
        role: str,
        model_backend,
        system_prompt: Optional[str] = None,
        tools: Optional[list] = None,
        max_context: int = 4096,
    ):
        self.agent_id = agent_id
        self.role = role
        self.model = model_backend
        self.system_prompt = system_prompt or f"You are a {role} agent."
        self.tools = tools or []
        self.max_context = max_context
        self._history: list[dict] = []
        self._state: dict[str, Any] = {}

    def set_state(self, key: str, value: Any):
        self._state[key] = value

    def get_state(self, key: str, default=None) -> Any:
        return self._state.get(key, default)

    def add_message(self, role: str, content: str):
        self._history.append({"role": role, "content": content})

    async def run(self, task: str, parent_context: Optional[str] = None) -> SubAgentResult:
        messages = [{"role": "system", "content": self.system_prompt}]
        if parent_context:
            messages.append({"role": "system", "content": f"Context from parent: {parent_context[:1000]}"})
        for msg in self._history[-10:]:
            messages.append(msg)
        messages.append({"role": "user", "content": task})

        try:
            output = await self.model.generate(messages=messages)
            self.add_message("user", task)
            self.add_message("assistant", output)
            return SubAgentResult(
                agent_id=self.agent_id,
                task=task,
                output=output,
                status="completed",
            )
        except Exception as e:
            logger.error(f"SubAgent '{self.agent_id}' failed: {e}")
            return SubAgentResult(
                agent_id=self.agent_id,
                task=task,
                output="",
                status="failed",
                error=str(e),
            )

    def reset_history(self):
        self._history = []
