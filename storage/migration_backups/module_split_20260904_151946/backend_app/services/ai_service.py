"""Clientes de IA y metadatos de uso para las automatizaciones de QA."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlparse

import httpx

from ..config.settings import Settings


ProviderName = Literal["ollama", "groq", "gemini"]


@dataclass(frozen=True)
class AIHttpResponse:
    """Cuerpo y encabezados útiles devueltos por un proveedor."""

    data: dict
    headers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class AICompletion:
    """Respuesta normalizada, independiente del proveedor."""

    provider: ProviderName
    model: str
    text: str
    usage: dict[str, int] = field(default_factory=dict)
    rate_limits: dict[str, str] = field(default_factory=dict)


class AIProviderError(RuntimeError):
    """Error clasificado para permitir activar el siguiente proveedor."""

    def __init__(self, provider: str, message: str, *, kind: str = "provider", status_code: int | None = None):
        super().__init__(message)
        self.provider = provider
        self.kind = kind
        self.status_code = status_code


class AIService:
    """Mantiene credenciales en backend y ofrece una interfaz única de texto."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def provider_statuses(self) -> list[dict[str, str | bool]]:
        """Devuelve configuración pública sin revelar claves."""

        ollama_key = bool(self.settings.ollama_api_key.get_secret_value().strip())
        local_ollama = bool(self.settings.ollama_local_base_url.strip())
        return [
            {
                "provider": "ollama",
                "configured": ollama_key or local_ollama,
                "model": self.settings.ollama_model,
                "mode": "cloud+local" if ollama_key and local_ollama else ("local" if local_ollama else "cloud"),
            },
            {
                "provider": "groq",
                "configured": bool(self.settings.groq_api_key.get_secret_value().strip()),
                "model": self.settings.groq_model,
                "mode": "cloud",
            },
            {
                "provider": "gemini",
                "configured": bool(self.settings.gemini_api_key.get_secret_value().strip()),
                "model": self.settings.gemini_model,
                "mode": "cloud",
            },
        ]

    async def generate(
        self,
        provider: ProviderName,
        prompt: str,
        *,
        system_instruction: str = "",
        model: str | None = None,
        local: bool = False,
    ) -> AICompletion:
        """Genera texto. `local=True` fuerza el servidor local de Ollama."""

        if not prompt.strip():
            raise ValueError("El mensaje para la IA no puede estar vacío.")
        if provider == "ollama":
            return await self._generate_ollama(prompt, system_instruction, model, local)
        if provider == "groq":
            return await self._generate_groq(prompt, system_instruction, model)
        if provider == "gemini":
            return await self._generate_gemini(prompt, system_instruction, model)
        raise ValueError("Proveedor de IA no soportado.")

    async def _generate_ollama(self, prompt: str, system_instruction: str, model: str | None, local: bool) -> AICompletion:
        key = "" if local else self._require_key("ollama")
        base_url = self.settings.ollama_local_base_url if local else self.settings.ollama_base_url
        endpoint = f"{base_url.rstrip('/')}/chat"
        payload = {
            "model": model or (self.settings.ollama_local_model if local else self.settings.ollama_model),
            "messages": self._messages(prompt, system_instruction),
            "stream": False,
        }
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        response = await self._post(endpoint, payload, headers)
        data, rate_limits = self._unpack_response(response)
        text = str(data.get("message", {}).get("content", "")).strip()
        return AICompletion(
            provider="ollama",
            model=str(data.get("model") or payload["model"]),
            text=self._require_text(text),
            usage=self._usage("ollama", data),
            rate_limits=rate_limits,
        )

    async def _generate_groq(self, prompt: str, system_instruction: str, model: str | None) -> AICompletion:
        key = self._require_key("groq")
        payload = {
            "model": model or self.settings.groq_model,
            "messages": self._messages(prompt, system_instruction),
            "temperature": 0.2,
        }
        response = await self._post(
            "https://api.groq.com/openai/v1/chat/completions",
            payload,
            {"Authorization": f"Bearer {key}"},
        )
        data, rate_limits = self._unpack_response(response)
        text = str(((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
        return AICompletion(
            provider="groq",
            model=str(data.get("model") or payload["model"]),
            text=self._require_text(text),
            usage=self._usage("groq", data),
            rate_limits=rate_limits,
        )

    async def _generate_gemini(self, prompt: str, system_instruction: str, model: str | None) -> AICompletion:
        key = self._require_key("gemini")
        combined_prompt = prompt.strip() if not system_instruction.strip() else f"{system_instruction.strip()}\n\n{prompt.strip()}"
        payload = {
            "model": model or self.settings.gemini_model,
            "store": False,
            "input": [{"type": "user_input", "content": [{"type": "text", "text": combined_prompt}]}],
        }
        response = await self._post(
            "https://generativelanguage.googleapis.com/v1beta/interactions",
            payload,
            {"x-goog-api-key": key},
        )
        data, rate_limits = self._unpack_response(response)
        return AICompletion(
            provider="gemini",
            model=str(data.get("model") or payload["model"]),
            text=self._require_text(self._gemini_text(data)),
            usage=self._usage("gemini", data),
            rate_limits=rate_limits,
        )

    async def _post(self, endpoint: str, payload: dict, headers: dict[str, str]) -> AIHttpResponse:
        provider = self._provider_for_endpoint(endpoint)
        try:
            async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
                response = await client.post(endpoint, json=payload, headers=headers)
                response.raise_for_status()
                rate_headers = {
                    key.lower(): value
                    for key, value in response.headers.items()
                    if key.lower().startswith("x-ratelimit-") or key.lower() in {"retry-after", "ratelimit-limit", "ratelimit-remaining", "ratelimit-reset"}
                }
                return AIHttpResponse(data=response.json(), headers=rate_headers)
        except httpx.HTTPStatusError as error:
            status = error.response.status_code
            message = self._provider_error_message(error.response)
            kind = "quota" if status == 429 or self._looks_like_quota(message) else "provider"
            raise AIProviderError(provider, message, kind=kind, status_code=status) from error
        except httpx.HTTPError as error:
            raise AIProviderError(provider, "No se pudo conectar con el proveedor de IA.", kind="network") from error

    def _require_key(self, provider: ProviderName) -> str:
        keys = {
            "ollama": self.settings.ollama_api_key,
            "groq": self.settings.groq_api_key,
            "gemini": self.settings.gemini_api_key,
        }
        key = keys[provider].get_secret_value().strip()
        if not key:
            raise AIProviderError(provider, f"{provider.title()} no está configurado en el archivo .env.", kind="configuration")
        return key

    @staticmethod
    def _messages(prompt: str, system_instruction: str) -> list[dict[str, str]]:
        messages = []
        if system_instruction.strip():
            messages.append({"role": "system", "content": system_instruction.strip()})
        messages.append({"role": "user", "content": prompt.strip()})
        return messages

    @staticmethod
    def _gemini_text(response: dict) -> str:
        direct_text = str(response.get("output_text") or "").strip()
        if direct_text:
            return direct_text
        for step in reversed(response.get("steps") or []):
            for content in step.get("content") or []:
                text = str(content.get("text") or "").strip()
                if text:
                    return text
        return ""

    @staticmethod
    def _unpack_response(response: AIHttpResponse | dict) -> tuple[dict, dict[str, str]]:
        # Mantiene compatibilidad con pruebas y extensiones que simulan solo el JSON.
        if isinstance(response, AIHttpResponse):
            return response.data, response.headers
        return response, {}

    @staticmethod
    def _usage(provider: ProviderName, response: dict) -> dict[str, int]:
        if provider == "ollama":
            values = {
                "input_tokens": response.get("prompt_eval_count"),
                "output_tokens": response.get("eval_count"),
            }
        elif provider == "groq":
            raw = response.get("usage") or {}
            values = {
                "input_tokens": raw.get("prompt_tokens"),
                "output_tokens": raw.get("completion_tokens"),
                "total_tokens": raw.get("total_tokens"),
            }
        else:
            raw = response.get("usageMetadata") or response.get("usage_metadata") or response.get("usage") or {}
            values = {
                "input_tokens": raw.get("promptTokenCount", raw.get("total_input_tokens")),
                "output_tokens": raw.get("candidatesTokenCount", raw.get("total_output_tokens")),
                "thought_tokens": raw.get("thoughtsTokenCount", raw.get("total_thought_tokens")),
                "total_tokens": raw.get("totalTokenCount", raw.get("total_tokens")),
            }
        usage = {key: int(value) for key, value in values.items() if isinstance(value, (int, float))}
        if "total_tokens" not in usage and {"input_tokens", "output_tokens"}.issubset(usage):
            usage["total_tokens"] = usage["input_tokens"] + usage["output_tokens"]
        return usage

    @staticmethod
    def _require_text(text: str) -> str:
        if not text:
            raise AIProviderError("unknown", "El proveedor de IA respondió sin contenido de texto.", kind="empty_response")
        return text

    @staticmethod
    def _provider_for_endpoint(endpoint: str) -> str:
        host = urlparse(endpoint).netloc.lower()
        if "groq" in host:
            return "groq"
        if "googleapis" in host or "generativelanguage" in host:
            return "gemini"
        return "ollama"

    @staticmethod
    def _looks_like_quota(message: str) -> bool:
        text = message.lower()
        return any(term in text for term in ("quota", "rate limit", "rate_limit", "too many", "resource exhausted", "tokens per"))

    @staticmethod
    def _provider_error_message(response: httpx.Response) -> str:
        try:
            detail = response.json()
            message = detail.get("error", {}).get("message") or detail.get("message") or detail.get("error")
        except ValueError:
            message = ""
        suffix = f" ({response.status_code})"
        return f"El proveedor de IA rechazó la solicitud{suffix}: {str(message)[:180]}" if message else f"El proveedor de IA rechazó la solicitud{suffix}."
