import json
from typing import AsyncGenerator, Optional
import httpx
from .base import ModelBackend


class OpenAIBackend(ModelBackend):
    name = "openai"

    def __init__(self, model: str = "gpt-4o-mini", api_key: str = "", base_url: str = "https://api.openai.com/v1"):
        self.model = model
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    async def generate(
        self,
        messages: list[dict],
        max_tokens: int = 256,
        temperature: float = 0.7,
        top_p: float = 1.0,
        stop: Optional[list[str]] = None,
    ) -> str:
        async with httpx.AsyncClient() as client:
            body = {
                "model": self.model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "top_p": top_p,
            }
            if stop:
                body["stop"] = stop
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers,
                json=body,
                timeout=120,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]

    async def generate_stream(
        self,
        messages: list[dict],
        max_tokens: int = 256,
        temperature: float = 0.7,
        top_p: float = 1.0,
        stop: Optional[list[str]] = None,
    ) -> AsyncGenerator[str, None]:
        async with httpx.AsyncClient() as client:
            body = {
                "model": self.model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "top_p": top_p,
                "stream": True,
            }
            if stop:
                body["stop"] = stop
            async with client.stream(
                "POST", f"{self.base_url}/chat/completions",
                headers=self._headers, json=body, timeout=120,
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        data = line[6:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                            delta = chunk["choices"][0].get("delta", {})
                            if "content" in delta:
                                yield delta["content"]
                        except json.JSONDecodeError:
                            continue

    async def health(self) -> dict:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{self.base_url}/models",
                    headers=self._headers,
                    timeout=5,
                )
                resp.raise_for_status()
                return {"status": "ok", "model": self.model}
        except Exception as e:
            return {"status": "error", "error": str(e)}
