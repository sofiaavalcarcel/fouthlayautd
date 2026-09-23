"""Contratos HTTP para el grabador visual del Bot de verificaciones."""

from typing import Literal

from pydantic import BaseModel, Field

from .bot import BotStep


class RecorderStartRequest(BaseModel):
    """Datos mínimos para abrir el navegador interactivo."""

    url: str = Field(min_length=1, max_length=2000)
    browser: Literal["chromium", "chrome", "firefox", "webkit"] = "chrome"
    steps: list[BotStep] = Field(default_factory=list, max_length=100)


class RecorderEvent(BaseModel):
    """Evento seleccionado por el usuario dentro de la página."""

    type: Literal["click", "check", "uncheck", "fill", "select", "scroll"]
    target: str = Field(min_length=1, max_length=500)
    value: str = Field(default="", max_length=1000)
    label: str = Field(default="", max_length=200)


class RecorderStartResponse(BaseModel):
    """Identificador que el renderer usará para consultar la grabación."""

    session_id: str
    status: Literal["RECORDING"]
    url: str


class RecorderEventsResponse(BaseModel):
    """Eventos acumulados desde la última consulta del renderer."""

    events: list[RecorderEvent]
    active: bool
    error: str | None = None


class RecorderStopResponse(BaseModel):
    """Flujo final listo para editar o ejecutar."""

    status: Literal["STOPPED"]
    url: str
    steps: list[BotStep]
