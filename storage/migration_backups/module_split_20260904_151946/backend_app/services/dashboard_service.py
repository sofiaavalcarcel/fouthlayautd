"""Reglas de aplicación para dashboard e historial."""

from pathlib import Path

from ..database.repository import ExecutionRepository


class DashboardService:
    """Orquesta consultas del dashboard sin exponer SQL a las rutas HTTP."""

    def __init__(self, database_path: Path):
        self.repository = ExecutionRepository(database_path)

    def summary(self) -> dict:
        """Devuelve las métricas de hoy y la última ejecución registrada."""

        return self.repository.get_dashboard_summary()

    def history(self, limit: int = 20) -> list[dict]:
        """Devuelve el historial limitado para evitar respuestas excesivamente grandes."""

        return self.repository.list_executions(limit)
