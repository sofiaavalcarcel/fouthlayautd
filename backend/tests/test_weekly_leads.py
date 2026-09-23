"""Pruebas del módulo independiente de envíos generales."""

import io

from fastapi.testclient import TestClient
from openpyxl import Workbook

from backend.app.config.settings import Settings
from backend.app.main import create_app
from backend.app.modules.weekly_auto.weekly_forms import (
    WeeklyFormsRunner,
    WeeklyFormsSpreadsheetService,
)
from backend.app.modules.weekly_auto.weekly_leads import (
    WeeklyLeadsRunner,
    WeeklyLeadsSpreadsheetService,
)


def _matrix() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "QA"
    sheet.append(["Country", "Nivel", "Activo de Test", "Location", "Cliente", "Lead"])
    sheet.append([
        "México",
        "Licenciatura",
        "https://example.com/programa",
        "Footer",
        "QA",
        "",
    ])
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def test_weekly_leads_uses_independent_adapters_without_copying_the_runner():
    assert issubclass(WeeklyLeadsRunner, WeeklyFormsRunner)
    assert issubclass(WeeklyLeadsSpreadsheetService, WeeklyFormsSpreadsheetService)
    assert WeeklyLeadsSpreadsheetService.BATCH_SIZE == 5
    assert WeeklyLeadsSpreadsheetService.BATCH_PAUSE_SECONDS == 60


def test_weekly_leads_has_its_own_preview_endpoint(tmp_path):
    app = create_app(Settings(database_path=tmp_path / "qa.db", storage_dir=tmp_path / "storage"))
    with TestClient(app) as client:
        response = client.post(
            "/api/weekly-auto/leads/spreadsheet-preview",
            files={"file": ("leads.xlsx", _matrix(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        schema_paths = app.openapi()["paths"]

    assert response.status_code == 200
    assert response.json()["sheets"][0]["total_rows"] == 1
    assert "/api/weekly-auto/leads/spreadsheet-preview" in schema_paths
    assert "/api/weekly-auto/leads/run" in schema_paths
