"""Pruebas del contrato HTTP inicial de FastAPI."""

from fastapi.testclient import TestClient
from pydantic import SecretStr

from backend.app.config.settings import Settings
from backend.app.main import create_app
from backend.app.modules.generic_bot.runner import BotRunner
from backend.app.modules.bot_nuevos_productos.runner import UtelInconcertRunner


def test_health_and_dashboard_endpoints(tmp_path):
    """La aplicación recién instalada responde salud y dashboard vacío."""

    settings = Settings(
        database_path=tmp_path / "api-test.db",
        storage_dir=tmp_path / "storage",
    )
    application = create_app(settings)

    with TestClient(application) as client:
        health_response = client.get("/api/health")
        dashboard_response = client.get("/api/dashboard/summary")

    assert health_response.status_code == 200
    assert health_response.json()["status"] == "ok"
    assert dashboard_response.status_code == 200
    assert dashboard_response.json()["total_today"] == 0


def test_web_frontend_is_served_by_fastapi(tmp_path):
    """La misma interfaz se puede abrir en un navegador sin depender de Electron."""

    settings = Settings(database_path=tmp_path / "web-test.db", storage_dir=tmp_path / "storage")
    application = create_app(settings)

    with TestClient(application) as client:
        page_response = client.get("/")
        module_response = client.get("/src/services/api.js")
        health_response = client.get("/api/health")

    assert page_response.status_code == 200
    assert "UTEL QA Automation" in page_response.text
    assert 'type="module"' in page_response.text
    assert module_response.status_code == 200
    assert "window.location.origin" in module_response.text
    assert health_response.status_code == 200


def test_ai_provider_status_never_returns_keys(tmp_path):
    """El endpoint de estado solo expone configuración y modelo."""

    settings = Settings(
        database_path=tmp_path / "api-test.db",
        storage_dir=tmp_path / "storage",
        ollama_api_key=SecretStr("ollama-secret"),
        groq_api_key=SecretStr("groq-secret"),
        gemini_api_key=SecretStr("gemini-secret"),
    )
    application = create_app(settings)

    with TestClient(application) as client:
        response = client.get("/api/ai/providers")

    assert response.status_code == 200
    payload = response.json()
    assert all(provider["configured"] for provider in payload["providers"])
    assert "ollama-secret" not in response.text
    assert "groq-secret" not in response.text
    assert "gemini-secret" not in response.text


def test_bot_run_returns_immediately_as_background_job(tmp_path, monkeypatch):
    """El endpoint acepta el bot sin esperar a que termine Playwright."""

    async def fake_run(self, config):
        return {
            "status": "PASS",
            "summary": "Bot finalizado correctamente.",
            "started_at": "2026-08-25T12:00:00",
            "finished_at": "2026-08-25T12:00:01",
            "duration_seconds": 1.0,
            "steps": [],
            "screenshots": [],
        }

    monkeypatch.setattr(BotRunner, "run", fake_run)
    application = create_app(Settings(database_path=tmp_path / "api-test.db", storage_dir=tmp_path / "storage"))

    with TestClient(application) as client:
        response = client.post(
            "/api/bots/run",
            json={"name": "bot de prueba", "url": "https://example.com", "steps": [{"type": "goto", "target": "https://example.com"}]},
        )
        assert response.status_code == 202
        job_id = response.json()["job_id"]

        status_response = client.get(f"/api/bots/runs/{job_id}")
        assert status_response.status_code == 200
        assert status_response.json()["status"] == "PASS"


def test_utel_inconcert_run_returns_background_job(tmp_path, monkeypatch):
    """El flujo UTEL/InConcert se lanza como job y no expone credenciales."""

    seen = []

    async def fake_run(self, config, should_stop=None):
        seen.append((config, should_stop))
        return {
            "status": "PASS",
            "summary": "Flujo UTEL/InConcert completado correctamente.",
            "started_at": "2026-08-25T12:00:00",
            "finished_at": "2026-08-25T12:00:04",
            "duration_seconds": 4.0,
            "country": config.country,
            "level": config.level,
            "modality": config.modality,
                "form_type": config.form_type,
                "lead_email": config.lead.email,
                "environment": config.environment,
                "dry_run": config.dry_run,
                "utel_submission": "success",
            "inconcert_login": "success",
            "lead_found": "success",
            "conversion_found": "success",
            "stages": [],
            "screenshots": [],
        }

    monkeypatch.setattr(UtelInconcertRunner, "run", fake_run)
    application = create_app(
        Settings(
            database_path=tmp_path / "api-test.db",
            storage_dir=tmp_path / "storage",
            inconcert_username="qa-user",
            inconcert_password="qa-password",
        )
    )

    with TestClient(application) as client:
        response = client.post(
            "/api/bots/utel-inconcert/run",
            json={
                "name": "QA Ecuador",
                "country": "Ecuador",
                "utel_url": "https://utel.edu.mx/ecuador/demo",
                "inconcert_url": "https://inconcert.example.test",
                "modality": "En linea",
                "level": "Licenciatura",
                "form_type": "lateral",
                "defer_crm_verification": True,
                "verification_only": True,
                "lead": {"name": "Lead QA", "email": "qa@example.com", "phone": "5549382716"},
            },
        )
        assert response.status_code == 202
        job_id = response.json()["job_id"]

        status_response = client.get(f"/api/bots/utel-inconcert/runs/{job_id}")
        assert status_response.status_code == 200
        payload = status_response.json()
        assert payload["status"] == "PASS"
        assert payload["result"]["lead_email"].startswith("Testing")
        assert payload["result"]["lead_email"].endswith("@testingUtel.com")
        assert "qa-password" not in status_response.text
        assert seen[0][0].defer_crm_verification is False
        assert seen[0][0].verification_only is False
        assert callable(seen[0][1])
