import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from backend.app.modules.bot_nuevos_productos.runner import UtelInconcertRunner, UtelQaError
from backend.app.config.settings import Settings


def runner(tmp_path):
    return UtelInconcertRunner(Settings(storage_dir=tmp_path, inconcert_username="qa", inconcert_password="test-secret"))


@pytest.mark.parametrize("url,expected", [
    ("https://crm.test/login?redirect=/mas/contact/people", False),
    ("https://crm.test/login?redirect=%2Fmas%2Fcontact%2Fpeople", False),
    ("https://crm.test/mas/contact/people", True),
    ("https://crm.test/mas/home", True),
])
def test_login_redirect_is_not_authenticated(url, expected):
    assert UtelInconcertRunner._is_crm_route(url) is expected


def test_relogin_before_search_uses_same_email(tmp_path):
    bot = runner(tmp_path)
    page = Mock(url="https://crm.test/login")
    bot._is_inconcert_login = AsyncMock(side_effect=[True, False])
    bot._login_inconcert = AsyncMock()
    bot._open_contacts = AsyncMock()
    bot._apply_contact_search = AsyncMock()
    bot._has_single_exact_name = AsyncMock(return_value=True)
    asyncio.run(bot._search_lead(page, "TestingN64@testingUtel.com", "Danilo325"))
    bot._login_inconcert.assert_awaited_once_with(page)
    bot._open_contacts.assert_awaited_once_with(page)
    bot._apply_contact_search.assert_awaited_once_with(page, "Email", "testingn64@testingutel.com")


def test_redirect_during_search_repeats_only_query(tmp_path):
    bot = runner(tmp_path)
    page = Mock()
    bot._is_inconcert_login = AsyncMock(side_effect=[False, True, False, False])
    bot._login_inconcert = AsyncMock()
    bot._open_contacts = AsyncMock()
    bot._apply_contact_search = AsyncMock(side_effect=[TimeoutError("login redirect"), None])
    bot._has_single_exact_name = AsyncMock(return_value=True)
    assert asyncio.run(bot._search_contact_with_session(page, "Email", "qa@test.example", "Danilo325"))
    bot._login_inconcert.assert_awaited_once()
    assert [c.args for c in bot._apply_contact_search.await_args_list] == [(page, "Email", "qa@test.example")] * 2


def test_persistent_session_loss_stops_after_one_relogin(tmp_path):
    bot = runner(tmp_path)
    bot._is_inconcert_login = AsyncMock(return_value=True)
    bot._login_inconcert = AsyncMock()
    bot._open_contacts = AsyncMock()
    bot._apply_contact_search = AsyncMock(side_effect=TimeoutError())
    with pytest.raises(UtelQaError, match="volvio al login") as caught:
        asyncio.run(bot._search_contact_with_session(Mock(), "Email", "qa@test.example", "Danilo325"))
    assert caught.value.stage == "inconcert_login"
    bot._login_inconcert.assert_awaited_once()


def test_unrelated_search_error_does_not_attempt_login(tmp_path):
    bot = runner(tmp_path)
    bot._is_inconcert_login = AsyncMock(return_value=False)
    bot._login_inconcert = AsyncMock()
    bot._apply_contact_search = AsyncMock(side_effect=TimeoutError("selector changed"))
    with pytest.raises(TimeoutError, match="selector changed"):
        asyncio.run(bot._search_contact_with_session(Mock(), "Email", "qa@test.example", "Danilo325"))
    bot._login_inconcert.assert_not_awaited()


def test_rejected_login_does_not_search_or_expose_credentials(tmp_path):
    bot = runner(tmp_path)
    field = Mock(wait_for=AsyncMock(), fill=AsyncMock(side_effect=RuntimeError("test-secret")))
    page = Mock(url="https://crm.test/login")
    page.locator.return_value = field
    with pytest.raises(UtelQaError) as caught:
        asyncio.run(bot._login_inconcert(page))
    assert caught.value.stage == "inconcert_login"
    assert "test-secret" not in str(caught.value)
    assert caught.value.__suppress_context__


def test_contacts_redirect_recovers_before_waiting_for_search(tmp_path):
    bot = runner(tmp_path)
    page = Mock(url="https://crm.test/mas/home", goto=AsyncMock(), wait_for_function=AsyncMock())
    search = Mock(wait_for=AsyncMock(), count=AsyncMock(return_value=1))
    page.locator.return_value.first = search
    bot._is_inconcert_login = AsyncMock(side_effect=[True, False])
    bot._login_inconcert = AsyncMock()
    asyncio.run(bot._open_contacts(page))
    bot._login_inconcert.assert_awaited_once()
    assert page.goto.await_count == 2
    # El resolver comprueba visibilidad y la etapa vuelve a esperar el campo
    # estable antes de continuar con la búsqueda.
    assert search.wait_for.await_count == 2


def test_login_does_not_fill_credentials_on_external_redirect(tmp_path):
    bot = runner(tmp_path)
    bot._crm_origin = "https://crm.test"
    page = Mock(url="https://other.test/login")
    with pytest.raises(UtelQaError, match="dominio distinto"):
        asyncio.run(bot._login_inconcert(page))
    page.locator.assert_not_called()
