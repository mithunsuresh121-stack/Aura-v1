"""
Orchestrator — lead agent that decomposes complex tasks and delegates to sub-agents.
Implements a hierarchical agent system where the lead agent:
1. Receives a complex user request
2. Breaks it down into subtasks
3. Spawns or routes to appropriate sub-agents
4. Collects results
5. Synthesizes final response
"""
import json
import asyncio
import logging
from typing import Any, Optional
from .sub_agent import SubAgent, SubAgentResult

logger = logging.getLogger("cortex.orchestration")

DECOMPOSITION_PROMPT = """You are an orchestrator agent. Your job is to break down complex user requests into subtasks that can be delegated to specialized sub-agents.

Available sub-agents and their roles:
{agent_roles}

For each subtask, respond with a JSON object:
```json
{
  "plan": "Brief explanation of your decomposition strategy",
  "subtasks": [
    {
      "agent_id": "name_of_agent",
      "task": "detailed description of what this agent should do",
      "depends_on": ["list of subtask indices this depends on, or empty list"]
    }
  ]
}
```

Consider which subtasks can run in parallel (no dependencies) vs sequentially (have dependencies).
"""

SYNTHESIS_PROMPT = """You are the lead orchestrator. Synthesize the results from your sub-agents into a cohesive final response for the user.

Original user request: {user_request}

Sub-agent results:
{sub_results}

Provide a complete, well-organized response that integrates all the work done by your sub-agents.
"""


class Orchestrator:
    def __init__(self, lead_model, agents: Optional[dict[str, SubAgent]] = None):
        self.lead_model = lead_model
        self._agents: dict[str, SubAgent] = agents or {}

    def register_agent(self, agent: SubAgent):
        self._agents[agent.agent_id] = agent
        logger.info(f"Registered sub-agent '{agent.agent_id}' ({agent.role})")

    async def execute(self, user_request: str, auto_delegate: bool = True) -> str:
        if not auto_delegate or len(self._agents) == 0:
            return await self._direct_response(user_request)

        plan = await self._decompose(user_request)
        subtasks = plan.get("subtasks", [])
        if not subtasks:
            return await self._direct_response(user_request)

        results = await self._execute_plan(subtasks)

        return await self._synthesize(user_request, results)

    async def _direct_response(self, user_request: str) -> str:
        return await self.lead_model.generate(messages=[
            {"role": "user", "content": user_request},
        ])

    async def _decompose(self, user_request: str) -> dict:
        roles = "\n".join(
            f"  - {aid}: {agent.role}" for aid, agent in self._agents.items()
        )
        prompt = DECOMPOSITION_PROMPT.format(agent_roles=roles)
        output = await self.lead_model.generate(messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"Decompose this task: {user_request}"},
        ])
        try:
            start = output.index("```json")
            end = output.index("```", start + 7)
            return json.loads(output[start + 7:end].strip())
        except (ValueError, json.JSONDecodeError):
            logger.warning("Failed to parse decomposition, using direct response")
            return {"subtasks": []}

    async def _execute_plan(self, subtasks: list[dict]) -> list[SubAgentResult]:
        results: list[Optional[SubAgentResult]] = [None] * len(subtasks)

        async def run_subtask(i: int, st: dict):
            agent_id = st["agent_id"]
            task = st["task"]
            agent = self._agents.get(agent_id)
            if not agent:
                return SubAgentResult(
                    agent_id=agent_id, task=task, output="",
                    status="failed", error=f"No agent with id '{agent_id}'",
                )
            parent_context = None
            for dep_idx in st.get("depends_on", []):
                dep_result = results[dep_idx]
                if dep_result and dep_result.status == "completed":
                    parent_context = (parent_context or "") + f"\n{dep_result.output}"
            return await agent.run(task, parent_context=parent_context)

        completed = set()
        while len(completed) < len(subtasks):
            batch = []
            for i, st in enumerate(subtasks):
                if i in completed:
                    continue
                deps = st.get("depends_on", [])
                if all(d in completed for d in deps):
                    batch.append((i, st))
            if not batch:
                logger.error("Deadlock in subtask dependencies")
                break
            batch_results = await asyncio.gather(*[
                run_subtask(i, st) for i, st in batch
            ])
            for (i, _), result in zip(batch, batch_results):
                results[i] = result
                completed.add(i)

        return [r for r in results if r is not None]

    async def _synthesize(self, user_request: str, results: list[SubAgentResult]) -> str:
        sub_results = "\n\n".join(
            f"[{r.agent_id}] (status: {r.status})\n{r.output}"
            for r in results
        )
        prompt = SYNTHESIS_PROMPT.format(
            user_request=user_request,
            sub_results=sub_results,
        )
        return await self.lead_model.generate(messages=[
            {"role": "system", "content": prompt},
        ])
