import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, Mock

import pytest

from backend.app.modules.bot_nuevos_productos.runner import UtelInconcertRunner, UtelQaError, UnconfirmedSubmission
from backend.app.config.settings import Settings
from backend.app.modules.bot_nuevos_productos.schemas import UtelQaConfig, UtelLead


@pytest.mark.parametrize("dry_run,login_failure", [(True, False), (False, False), (False, True)])
@pytest.mark.parametrize("uncertain,missing", [(False, False), (True, False), (True, True)])
@pytest.mark.parametrize("session_expired", [False, True])
def test_deploy_retrieves_verified_lead_without_resending(tmp_path, dry_run, login_failure, uncertain, missing, session_expired):
    runner = UtelInconcertRunner(Settings(storage_dir=tmp_path, inconcert_username="test", inconcert_password="test"))
    page = Mock(url="https://utel.test")
    context = Mock(new_page=AsyncMock(return_value=page), close=AsyncMock())
    browser = Mock(new_context=AsyncMock(return_value=context), close=AsyncMock())
    playwright = Mock()
    playwright.chromium.launch = AsyncMock(return_value=browser)

    @asynccontextmanager
    async def runtime(*args):
        yield playwright

    runner._playwright = runtime
    runner._close_open_session = AsyncMock()
    runner._safe_screenshot = AsyncMock(return_value=None)
    original_search = runner._search_lead
    for name in ("_open_utel", "_navigate_utel", "_find_utel_form", "_fill_utel_form", "_open_inconcert",
                 "_login_inconcert", "_open_contacts", "_submit_utel_form", "_search_lead", "_confirm_conversion"):
        setattr(runner, name, AsyncMock())
    if login_failure:
        runner._login_inconcert.side_effect = UtelQaError("inconcert_login", "CRM no disponible")
    if uncertain:
        runner._submit_utel_form.side_effect = UnconfirmedSubmission("utel_submit", "Sin confirmacion")
    if missing:
        runner._search_lead.side_effect = UtelQaError("inconcert_search", "Lead no encontrado")
    elif session_expired:
        runner._search_lead = original_search
        runner._is_inconcert_login = AsyncMock(side_effect=[True, False])
        runner._apply_contact_search = AsyncMock()
        runner._has_single_exact_name = AsyncMock(return_value=True)
    async def manage(*args):
        runner.lead_url = "https://crm.test/mas/contact/people/view/123"
    runner._open_manage = AsyncMock(side_effect=manage)
    config = UtelQaConfig(country="Mexico", utel_url="https://utel.test", inconcert_url="https://crm.test",
                          modality="En linea", level="Licenciatura", form_type="footer",
                          workflow_mode="form_validation", dry_run=dry_run, lead=UtelLead())
    result = asyncio.run(runner.run(config))
    if dry_run or login_failure:
        runner._submit_utel_form.assert_not_awaited()
        assert result["lead_url"] is None
    elif missing:
        runner._submit_utel_form.assert_awaited_once()
        runner._open_manage.assert_not_awaited()
        assert result["lead_url"] is None
    else:
        runner._submit_utel_form.assert_awaited_once()
        runner._open_manage.assert_awaited_once()
        if session_expired:
            assert runner._login_inconcert.await_count == 2
            assert runner._open_contacts.await_count == 2
        stages = [s.stage for s in result["stages"]]
        assert stages.index("inconcert_login") < stages.index("inconcert_manage")
        if not uncertain:
            assert stages.index("inconcert_login") < stages.index("utel_submit")
        else:
            assert "sin reenviar" in runner.status_flags["utel_submission_message"]
        assert result["lead_url"].endswith("/123")
    assert result["status"] == ("FAIL" if not dry_run and (login_failure or missing) else "PASS")
