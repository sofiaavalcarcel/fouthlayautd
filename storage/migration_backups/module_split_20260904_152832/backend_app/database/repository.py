"""Consultas de persistencia relacionadas con las ejecuciones."""

from datetime import date
from pathlib import Path
from typing import Any

from .connection import connection_rows, get_connection


class ExecutionRepository:
    """Centraliza SQL para que los servicios no dependan de detalles de SQLite."""

    def __init__(self, database_path: Path):
        self.database_path = database_path

    def get_dashboard_summary(self) -> dict[str, Any]:
        """Calcula las métricas del dashboard para el día local actual."""

        today = date.today().isoformat()
        with get_connection(self.database_path) as connection:
            counts = connection.execute(
                """
                SELECT
                    COUNT(*) AS total_today,
                    SUM(CASE WHEN status = 'SUCCESS' THEN 1 ELSE 0 END) AS successful_today,
                    SUM(CASE WHEN status = 'FAIL' THEN 1 ELSE 0 END) AS failed_today,
                    SUM(CASE WHEN status = 'WARNING' THEN 1 ELSE 0 END) AS changes_detected_today
                FROM executions
                WHERE substr(started_at, 1, 10) = ?
                """,
                (today,),
            ).fetchone()
            latest = connection_rows(
                connection,
                """
                SELECT id, automation_type, name, status, started_at, finished_at,
                       duration_seconds, summary, error_message, evidence_json
                FROM executions
                ORDER BY started_at DESC, id DESC
                LIMIT 1
                """,
            )

        return {
            "total_today": counts["total_today"] or 0,
            "successful_today": counts["successful_today"] or 0,
            "failed_today": counts["failed_today"] or 0,
            "changes_detected_today": counts["changes_detected_today"] or 0,
            "latest_execution": latest[0] if latest else None,
        }

    def list_executions(self, limit: int = 20) -> list[dict[str, Any]]:
        """Devuelve las ejecuciones más recientes para la pantalla de historial."""

        safe_limit = max(1, min(limit, 100))
        with get_connection(self.database_path) as connection:
            return connection_rows(
                connection,
                """
                SELECT id, automation_type, name, status, started_at, finished_at,
                       duration_seconds, summary, error_message, evidence_json
                FROM executions
                ORDER BY started_at DESC, id DESC
                LIMIT ?
                """,
                (safe_limit,),
            )

    def create_execution(self, execution: dict[str, Any]) -> int:
        """Guarda una ejecución; será usado por las automatizaciones desde la Fase 2."""

        fields = (
            "automation_type",
            "name",
            "status",
            "started_at",
            "finished_at",
            "duration_seconds",
            "summary",
            "error_message",
            "evidence_json",
            "created_at",
        )
        values = tuple(execution.get(field) for field in fields)
        placeholders = ", ".join("?" for _ in fields)
        with get_connection(self.database_path) as connection:
            cursor = connection.execute(
                f"INSERT INTO executions ({', '.join(fields)}) VALUES ({placeholders})",
                values,
            )
            return int(cursor.lastrowid)
