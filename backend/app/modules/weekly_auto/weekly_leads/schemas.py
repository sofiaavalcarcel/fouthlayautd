"""Contratos propios para el envío general de leads."""

from ..weekly_forms.schemas import WeeklyFormsCaseConfig


class WeeklyLeadsCaseConfig(WeeklyFormsCaseConfig):
    """Mantiene los mismos campos de Weekly Forms con identidad independiente."""
