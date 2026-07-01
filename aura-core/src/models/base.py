from abc import ABC, abstractmethod
from typing import AsyncGenerator, Optional


class ModelBackend(ABC):
    name: str = "base"

    @abstractmethod
    async def generate(
        self,
        messages: list[dict],
        max_tokens: int = 256,
        temperature: float = 0.7,
        top_p: float = 1.0,
        stop: Optional[list[str]] = None,
    ) -> str:
        ...

    @abstractmethod
    async def generate_stream(
        self,
        messages: list[dict],
        max_tokens: int = 256,
        temperature: float = 0.7,
        top_p: float = 1.0,
        stop: Optional[list[str]] = None,
    ) -> AsyncGenerator[str, None]:
        ...

    @abstractmethod
    async def health(self) -> dict:
        ...
