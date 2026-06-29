import json
import httpx
from typing import AsyncGenerator, Optional
from .base import ModelBackend


class OllamaBackend(ModelBackend):
    name = "ollama"

    def __init__(self, model: str = "llama3.2", base_url: str = "http://localhost:11434"):
        self.model = model
        self.base_url = base_url.rstrip("/")

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
                "stream": False,
                "options": {
                    "num_predict": max_tokens,
                    "temperature": temperature,
                    "top_p": top_p,
                },
            }
            if stop:
                body["options"]["stop"] = stop
            resp = await client.post(f"{self.base_url}/api/chat", json=body, timeout=120)
            resp.raise_for_status()
            return resp.json()["message"]["content"]

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
                "stream": True,
                "options": {
                    "num_predict": max_tokens,
                    "temperature": temperature,
                    "top_p": top_p,
                },
            }
            if stop:
                body["options"]["stop"] = stop
            async with client.stream("POST", f"{self.base_url}/api/chat", json=body, timeout=120) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    data = json.loads(line)
                    if "message" in data and "content" in data["message"]:
                        yield data["message"]["content"]
                    if data.get("done"):
                        break

    async def health(self) -> dict:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(f"{self.base_url}/api/tags", timeout=5)
                resp.raise_for_status()
                models = [m["name"] for m in resp.json().get("models", [])]
                return {"status": "ok", "model": self.model, "available_models": models}
        except Exception as e:
            return {"status": "error", "error": str(e)}
