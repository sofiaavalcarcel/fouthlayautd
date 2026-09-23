"""Compatibilidad pública para la automatización existente de Weekly Photos."""

from .weekly_photos.runner import WeeklyAutoError, WeeklyAutoRunner

__all__ = ["WeeklyAutoError", "WeeklyAutoRunner"]
