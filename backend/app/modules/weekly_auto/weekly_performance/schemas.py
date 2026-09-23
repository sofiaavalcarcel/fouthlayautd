"""Contratos de entrada para Weekly Performance."""

from pydantic import BaseModel, Field, field_validator


class WeeklyPerformanceConfig(BaseModel):
    """Configuración segura del procesamiento PageSpeed sobre un Excel."""

    sheet_name: str = Field(default="Hoja 1", min_length=1, max_length=120)
    max_workers: int = Field(default=8, ge=1, le=16)

    @field_validator("sheet_name")
    @classmethod
    def _clean_sheet_name(cls, value: str) -> str:
        return value.strip()
