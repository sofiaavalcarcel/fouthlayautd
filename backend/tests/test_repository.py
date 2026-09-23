"""Pruebas de la persistencia usada por el dashboard."""

from datetime import datetime

from backend.app.database.connection import initialize_database
from backend.app.database.repository import ExecutionRepository


def test_dashboard_starts_empty(tmp_path):
    """Una instalación nueva debe mostrar métricas en cero y ninguna ejecución."""

    database_path = tmp_path / "test.db"
    initialize_database(database_path)
    summary = ExecutionRepository(database_path).get_dashboard_summary()

    assert summary["total_today"] == 0
    assert summary["successful_today"] == 0
    assert summary["latest_execution"] is None


def test_dashboard_counts_execution_statuses(tmp_path):
    """El dashboard cuenta estados y conserva la ejecución más reciente."""

    database_path = tmp_path / "test.db"
    initialize_database(database_path)
    repository = ExecutionRepository(database_path)
    now = datetime.now().isoformat(timespec="seconds")

    for status in ("SUCCESS", "FAIL", "WARNING"):
        repository.create_execution(
            {
                "automation_type": "test",
                "name": f"Ejecución {status}",
                "status": status,
                "started_at": now,
                "finished_at": now,
                "duration_seconds": 1.5,
                "summary": "Ejecución de prueba",
                "error_message": None,
                "evidence_json": None,
                "created_at": now,
            }
        )

    summary = repository.get_dashboard_summary()
    assert summary["total_today"] == 3
    assert summary["successful_today"] == 1
    assert summary["failed_today"] == 1
    assert summary["changes_detected_today"] == 1
    assert summary["latest_execution"]["status"] == "WARNING"
