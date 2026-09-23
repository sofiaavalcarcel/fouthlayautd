"""Pruebas unitarias sin llamadas a proveedores externos."""

import asyncio

import pytest
from pydantic import SecretStr

from backend.app.config.settings import Settings
from backend.app.services.ai_service import AIHttpResponse, AIService


def test_groq_response_is_normalized_without_network(tmp_path, monkeypatch):
    settings = Settings(
        database_path=tmp_path / "ai.db",
        storage_dir=tmp_path / "storage",
        groq_api_key=SecretStr("test-key"),
    )
    service = AIService(settings)

    async def fake_post(endpoint, payload, headers):
        assert endpoint.endswith("/chat/completions")
        assert headers["Authorization"] == "Bearer test-key"
        return AIHttpResponse(
            data={
                "model": payload["model"],
                "choices": [{"message": {"content": "respuesta de prueba"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
            },
            headers={"x-ratelimit-remaining-tokens": "990"},
        )

    monkeypatch.setattr(service, "_post", fake_post)
    result = asyncio.run(service.generate("groq", "Hola"))

    assert result.provider == "groq"
    assert result.text == "respuesta de prueba"
    assert result.usage["total_tokens"] == 14
    assert result.rate_limits["x-ratelimit-remaining-tokens"] == "990"


def test_ollama_accepts_text_message_shape_without_attribute_error(tmp_path, monkeypatch):
    settings = Settings(
        database_path=tmp_path / "ollama.db",
        storage_dir=tmp_path / "storage",
        ollama_local_base_url="http://ollama.test/api",
        ollama_local_model="qa-model",
    )
    service = AIService(settings)

    async def fake_post(endpoint, payload, headers):
        return AIHttpResponse(
            data={"model": payload["model"], "message": "5512345678"},
            headers={},
        )

    monkeypatch.setattr(service, "_post", fake_post)
    result = asyncio.run(service.generate("ollama", "Genera un teléfono", local=True))

    assert result.text == "5512345678"


def test_ollama_accepts_plain_text_response_shape(tmp_path, monkeypatch):
    settings = Settings(
        database_path=tmp_path / "ollama-plain.db",
        storage_dir=tmp_path / "storage",
        ollama_local_base_url="http://ollama.test/api",
        ollama_local_model="qa-model",
    )
    service = AIService(settings)

    async def fake_post(endpoint, payload, headers):
        return AIHttpResponse(data="5512345678", headers={})

    monkeypatch.setattr(service, "_post", fake_post)
    result = asyncio.run(service.generate("ollama", "Genera un teléfono", local=True))

    assert result.text == "5512345678"


def test_unconfigured_provider_fails_before_network(tmp_path):
    service = AIService(
        Settings(
            database_path=tmp_path / "ai.db",
            storage_dir=tmp_path / "storage",
            ollama_api_key=SecretStr(""),
            groq_api_key=SecretStr(""),
            gemini_api_key=SecretStr(""),
        )
    )

    with pytest.raises(RuntimeError, match="Ollama"):
        asyncio.run(service.generate("ollama", "Hola"))
