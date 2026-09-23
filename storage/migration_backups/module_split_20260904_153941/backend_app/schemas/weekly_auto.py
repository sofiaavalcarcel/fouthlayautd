"""Esquemas para la automatización de captura semanal de URLs."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class WeeklyAutoConfig(BaseModel):
    """Parámetros de ejecución para el módulo \"weekly auto\"."""

    name: str = Field(default="Weekly Auto", min_length=1, max_length=120)
    urls: list[str] = Field(default_factory=list)
    use_default_urls: bool = True
    browser: Literal["chromium", "chrome", "firefox", "webkit"] = "chromium"
    headless: bool = True
    keep_browser_open: bool = False
    viewport_width: int = 1280
    viewport_height: int = 680
    inter_url_delay_seconds: int = 0
    scroll_pause_ms: int = 2000
    settle_wait_ms: int = 1000
    max_urls: int | None = None

    @field_validator("inter_url_delay_seconds", "scroll_pause_ms", "settle_wait_ms")
    @classmethod
    def _non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("El valor debe ser mayor o igual a 0.")
        return value

    @field_validator("viewport_width", "viewport_height")
    @classmethod
    def _valid_viewport(cls, value: int) -> int:
        if value < 200 or value > 7680:
            raise ValueError("El tamaño de ventana debe estar entre 200 y 7680 px.")
        return value


class WeeklyAutoRunResult(BaseModel):
    """Resumen del procesamiento de una URL."""

    index: int
    url: str
    status: Literal["PASS", "FAIL", "SKIPPED"]
    message: str
    screenshot: str | None = None
    elapsed_seconds: float


class WeeklyAutoJobResult(BaseModel):
    """Estado persistible del flujo semanal."""

    status: Literal["PASS", "FAIL", "CANCELLED"]
    summary: str
    started_at: str
    finished_at: str
    duration_seconds: float
    total_urls: int
    completed: int
    successful: int
    failed: int
    skipped: int
    results: list[WeeklyAutoRunResult]
    screenshots: list[str]


class WeeklyAutoJobResponse(BaseModel):
    """Estructura de consulta para un job en background."""

    job_id: str
    name: str
    status: Literal["QUEUED", "RUNNING", "PASS", "FAIL", "CANCELLED"]
    started_at: str
    total_urls: int | None = None
    completed: int = 0
    successful: int = 0
    failed: int = 0
    skipped: int = 0
    current_url: str | None = None
    current_index: int | None = None
    summary: str | None = None
    result: WeeklyAutoJobResult | None = None
