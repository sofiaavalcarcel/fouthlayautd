"""Runner de envíos generales basado en el flujo estable de Weekly Forms."""

from ..weekly_forms.runner import WeeklyFormsRunner


class WeeklyLeadsRunner(WeeklyFormsRunner):
    """Expone el flujo de formularios como una automatización separada."""
