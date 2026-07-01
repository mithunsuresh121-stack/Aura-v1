"""Tests for model backends — Ollama, OpenAI (mocked)."""
import pytest
from models.ollama import OllamaBackend
from models.openai import OpenAIBackend
from models.registry import ModelRegistry


class TestOllamaBackend:
    def test_init_defaults(self):
        b = OllamaBackend()
        assert b.model == "llama3.2"
        assert b.base_url == "http://localhost:11434"

    def test_init_custom(self):
        b = OllamaBackend(model="llama3.1:8b", base_url="http://10.0.0.1:11434")
        assert b.model == "llama3.1:8b"
        assert b.base_url == "http://10.0.0.1:11434"

    @pytest.mark.asyncio
    async def test_health_no_ollama(self):
        b = OllamaBackend(base_url="http://localhost:1")
        result = await b.health()
        assert result["status"] == "error"
        assert "error" in result

    @pytest.mark.asyncio
    async def test_generate_no_ollama(self):
        b = OllamaBackend(base_url="http://localhost:1")
        with pytest.raises(Exception):
            await b.generate([{"role": "user", "content": "hi"}])


class TestOpenAIBackend:
    def test_init_defaults(self):
        b = OpenAIBackend()
        assert b.model == "gpt-4o-mini"
        assert b.base_url == "https://api.openai.com/v1"

    def test_init_custom(self):
        b = OpenAIBackend(
            model="gpt-4",
            api_key="sk-test",
            base_url="https://custom.example.com/v1",
        )
        assert b.model == "gpt-4"
        assert "Authorization" in b._headers
        assert b._headers["Authorization"] == "Bearer sk-test"

    @pytest.mark.asyncio
    async def test_health_no_key(self):
        b = OpenAIBackend(api_key="")
        result = await b.health()
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_generate_no_key(self):
        b = OpenAIBackend(api_key="")
        with pytest.raises(Exception):
            await b.generate([{"role": "user", "content": "hi"}])


class TestModelRegistry:
    def test_init_empty(self, tmp_path):
        cfg = tmp_path / "empty.json"
        cfg.write_text("{}")
        r = ModelRegistry(str(cfg))
        assert r.available == []

    def test_init_with_config(self, tmp_path):
        cfg = tmp_path / "models.json"
        cfg.write_text("""
        {
            "default": "ollama",
            "providers": {
                "ollama": {
                    "type": "ollama",
                    "model": "llama3.2",
                    "enabled": true
                },
                "openai": {
                    "type": "openai",
                    "model": "gpt-4o-mini",
                    "enabled": false
                }
            }
        }
        """)
        r = ModelRegistry(str(cfg))
        assert "ollama" in r.available
        assert "openai" not in r.available
        assert r.default == "ollama"

    def test_register(self, tmp_path):
        cfg = tmp_path / "empty.json"
        cfg.write_text("{}")
        r = ModelRegistry(str(cfg))
        b = OllamaBackend()
        r.register("my-ollama", b)
        assert "my-ollama" in r.available

    def test_get_by_name(self, tmp_path):
        cfg = tmp_path / "empty.json"
        cfg.write_text("{}")
        r = ModelRegistry(str(cfg))
        b = OllamaBackend()
        r.register("test", b)
        assert r.get("test") is b

    def test_get_default(self, tmp_path):
        cfg = tmp_path / "empty.json"
        cfg.write_text("{}")
        r = ModelRegistry(str(cfg))
        b = OllamaBackend()
        r.register("test", b)
        r.default = "test"
        assert r.get() is b

    def test_get_missing(self, tmp_path):
        cfg = tmp_path / "empty.json"
        cfg.write_text("{}")
        r = ModelRegistry(str(cfg))
        with pytest.raises(ValueError, match="not registered"):
            r.get("nonexistent")

    def test_get_none_when_empty(self, tmp_path):
        cfg = tmp_path / "empty.json"
        cfg.write_text("{}")
        r = ModelRegistry(str(cfg))
        with pytest.raises(ValueError):
            r.get()

    def test_default_setter(self, tmp_path):
        cfg = tmp_path / "empty.json"
        cfg.write_text("{}")
        r = ModelRegistry(str(cfg))
        b1 = OllamaBackend()
        b2 = OllamaBackend(model="llama3.1:8b")
        r.register("ollama1", b1)
        r.register("ollama2", b2)
        r.default = "ollama2"
        assert r.get() is b2

    def test_default_setter_invalid(self, tmp_path):
        cfg = tmp_path / "empty.json"
        cfg.write_text("{}")
        r = ModelRegistry(str(cfg))
        with pytest.raises(ValueError):
            r.default = "nonexistent"
