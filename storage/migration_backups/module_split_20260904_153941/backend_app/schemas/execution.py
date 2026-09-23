"""Modelos de respuesta pública relacionados con ejecuciones."""

from typing import Any

from pydantic import BaseModel, ConfigDict


class ExecutionSummary(BaseModel):
    """Representa una ejecución en el dashboard o historial."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    automation_type: str
    name: str
    status: str
    started_at: str
    finished_at: str | None = None
    duration_seconds: float | None = None
    summary: str | None = None
    error_message: str | None = None
    evidence_json: str | None = None


class DashboardSummary(BaseModel):
    """Métricas resumidas que necesita la pantalla principal."""

    total_today: int
    successful_today: int
    failed_today: int
    changes_detected_today: int
    latest_execution: ExecutionSummary | None = None


class HealthResponse(BaseModel):
    """Respuesta sencilla para comprobar si FastAPI está disponible."""

    status: str
    service: str
    timestamp: str


class ExecutionListResponse(BaseModel):
    """Respuesta explícita para mantener consistente el contrato de historial."""

    items: list[ExecutionSummary]
    total: int
