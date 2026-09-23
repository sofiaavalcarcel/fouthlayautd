"""Contratos seguros para conocer el estado de proveedores de IA."""

from typing import Literal

from pydantic import BaseModel, Field


AIProviderName = Literal["ollama", "groq", "gemini"]


class AIProviderStatus(BaseModel):
    """Estado público de un proveedor, sin claves ni detalles sensibles."""

    provider: AIProviderName
    configured: bool
    model: str
    mode: str = "cloud"


class AIProvidersResponse(BaseModel):
    """Lista de conexiones disponibles para las automatizaciones futuras."""

    providers: list[AIProviderStatus]


class AICompletionRequest(BaseModel):
    """Solicitud interna para las automatizaciones que usarán IA."""

    provider: AIProviderName
    prompt: str = Field(min_length=1, max_length=120_000)
    system_instruction: str = Field(default="", max_length=20_000)
    model: str | None = Field(default=None, min_length=1, max_length=120)


class AICompletionResponse(BaseModel):
    """Respuesta normalizada sin datos de autenticación."""

    provider: AIProviderName
    model: str
    text: str
    usage: dict[str, int] = Field(default_factory=dict)
    rate_limits: dict[str, str] = Field(default_factory=dict)
