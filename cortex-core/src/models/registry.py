"""Model registry — manages multiple model backends with runtime switching."""
import json
import os
import logging
from typing import Optional
from .base import ModelBackend
from .ollama import OllamaBackend
from .openai import OpenAIBackend
from .gemini import GeminiBackend
from .local import LocalBackend

logger = logging.getLogger("cortex.models")


def load_config(path: str = "") -> dict:
    paths = [path] if path else []
    paths.extend([
        os.environ.get("CORTEX_MODELS_CONFIG", ""),
        os.path.expanduser("~/.config/aura/models.json"),
        os.path.join(os.getcwd(), "models.json"),
    ]
    )
    for p in paths:
        if p and os.path.exists(p):
            with open(p) as f:
                return json.load(f)
    return {}


class ModelRegistry:
    def __init__(self, config_path: str = ""):
        self._backends: dict[str, ModelBackend] = {}
        self._default: Optional[str] = None
        config = load_config(config_path)
        self._build_from_config(config)

    def _build_from_config(self, config: dict):
        providers = config.get("providers", {})
        for name, cfg in providers.items():
            provider_type = cfg.get("type", "").lower()
            enabled = cfg.get("enabled", True)
            if not enabled:
                continue
            try:
                if provider_type == "ollama":
                    backend = OllamaBackend(
                        model=cfg.get("model", "llama3.2"),
                        base_url=cfg.get("base_url", "http://localhost:11434"),
                    )
                elif provider_type == "openai":
                    backend = OpenAIBackend(
                        model=cfg.get("model", "gpt-4o-mini"),
                        api_key=cfg.get("api_key", os.environ.get("OPENAI_API_KEY", "")),
                        base_url=cfg.get("base_url", "https://api.openai.com/v1"),
                    )
                elif provider_type == "gemini":
                    backend = GeminiBackend(
                        model=cfg.get("model", "gemini-2.0-flash"),
                        api_key=cfg.get("api_key", os.environ.get("GEMINI_API_KEY", "")),
                    )
                else:
                    logger.warning(f"Unknown model type '{provider_type}' for '{name}'")
                    continue
                self.register(name, backend)
                logger.info(f"Registered model '{name}' ({provider_type}: {backend.model})")
            except Exception as e:
                logger.error(f"Failed to register model '{name}': {e}")

        self._default = config.get("default", next(iter(self._backends.keys()), None))

    def register(self, name: str, backend: ModelBackend):
        self._backends[name] = backend

    def register_local(self, name: str, model, tokenizer, device: str = "cpu"):
        self._backends[name] = LocalBackend(model, tokenizer, device)

    def get(self, name: Optional[str] = None) -> ModelBackend:
        if name is None:
            name = self._default
        if name is None or name not in self._backends:
            available = list(self._backends.keys())
            raise ValueError(f"Model '{name}' not registered. Available: {available}")
        return self._backends[name]

    @property
    def default(self) -> Optional[str]:
        return self._default

    @default.setter
    def default(self, name: str):
        if name not in self._backends:
            raise ValueError(f"Model '{name}' not registered")
        self._default = name

    @property
    def available(self) -> list[str]:
        return list(self._backends.keys())

    async def health_all(self) -> dict[str, dict]:
        results = {}
        for name, backend in self._backends.items():
            try:
                results[name] = await backend.health()
            except Exception as e:
                results[name] = {"status": "error", "error": str(e)}
        return results
