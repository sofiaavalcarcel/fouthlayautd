import asyncio
from unittest.mock import AsyncMock, Mock

from backend.app.modules.bot_nuevos_productos.runner import UtelInconcertRunner
from backend.app.config.settings import Settings
from backend.app.modules.bot_nuevos_productos.schemas import UtelLead, UtelQaConfig


def _config(form_type: str) -> UtelQaConfig:
    return UtelQaConfig(
        country="Mexico",
        utel_url="https://utel.edu.mx/doctorado-en-linea",
        modality="En linea",
        level="Doctorado",
        form_type=form_type,
        workflow_mode="form_validation",
        lead=UtelLead(),
    )


def test_footer_and_lateral_stay_on_the_excel_url():
    for form_type in ("footer", "lateral"):
        runner = UtelInconcertRunner(Settings())
        runner._click_first_program_card = AsyncMock()
        page = AsyncMock()

        asyncio.run(runner._navigate_form_validation(page, _config(form_type)))

        runner._click_first_program_card.assert_not_awaited()
        page.wait_for_load_state.assert_not_awaited()


def test_tarjeta_opens_a_program_before_looking_for_the_form():
    runner = UtelInconcertRunner(Settings())
    runner._click_first_program_card = AsyncMock()
    runner._capture_selected_program = AsyncMock()
    page = AsyncMock()

    asyncio.run(runner._navigate_form_validation(page, _config("tarjeta")))

    runner._click_first_program_card.assert_awaited_once_with(page)
    page.wait_for_load_state.assert_awaited_once_with("domcontentloaded")
    runner._capture_selected_program.assert_awaited_once_with(page)


def test_footer_scrolls_before_returning_form(monkeypatch):
    runner = UtelInconcertRunner(Settings())
    form = AsyncMock()
    form.count.return_value = 1
    form.is_visible.return_value = True
    page = Mock()
    page.locator.return_value.first = form
    page.locator.return_value.inner_text = AsyncMock(return_value="Formulario UTEL")
    monkeypatch.setattr("backend.app.modules.bot_nuevos_productos.runner.asyncio.sleep", AsyncMock())
    result = asyncio.run(runner._find_utel_form(page, _config("footer")))
    assert result is form
    form.scroll_into_view_if_needed.assert_awaited_once()
    assert form.is_visible.await_count == 2


def test_tarjeta_does_not_scroll_before_returning_form(monkeypatch):
    runner = UtelInconcertRunner(Settings())
    form = AsyncMock()
    form.count.return_value = 1
    form.is_visible.return_value = True
    body = AsyncMock()
    body.inner_text.return_value = "Página UTEL"
    page = Mock()
    page.locator.side_effect = lambda selector: body if selector == "body" else Mock(first=form)
    monkeypatch.setattr("backend.app.modules.bot_nuevos_productos.runner.asyncio.sleep", AsyncMock())

    result = asyncio.run(runner._find_utel_form(page, _config("tarjeta")))

    assert result is form
    form.scroll_into_view_if_needed.assert_not_awaited()


def test_delayed_tarjeta_is_requeried_instead_of_reported_missing(monkeypatch):
    runner = UtelInconcertRunner(Settings())
    runner.FORM_POLL_INTERVAL_SECONDS = 0.001
    form = AsyncMock()
    form.count.return_value = 1
    form.is_visible.side_effect = [False, False, True, True]
    body = AsyncMock()
    body.inner_text.return_value = "Página UTEL"
    container = Mock(first=form)
    page = Mock()
    page.locator.side_effect = lambda selector: body if selector == "body" else container
    page.reload = AsyncMock()
    monkeypatch.setattr("backend.app.modules.bot_nuevos_productos.runner.asyncio.sleep", AsyncMock())

    result = asyncio.run(runner._find_utel_form(page, _config("tarjeta")))

    assert result is form
    assert form.is_visible.await_count == 3
    page.reload.assert_not_awaited()


def test_tarjeta_reloads_once_before_failing(monkeypatch):
    runner = UtelInconcertRunner(Settings())
    runner.FORM_WAIT_TIMEOUT_MS = 5
    runner.FORM_RECHECK_TIMEOUT_MS = 5
    runner.FORM_POLL_INTERVAL_SECONDS = 0.001
    hidden_form = AsyncMock()
    hidden_form.count.return_value = 0
    visible_form = AsyncMock()
    visible_form.count.return_value = 1
    visible_form.is_visible.return_value = True
    body = AsyncMock()
    body.inner_text.return_value = "Página UTEL"
    state = {"reloaded": False}
    page = Mock()

    def locator(selector):
        if selector == "body":
            return body
        return Mock(first=visible_form if state["reloaded"] else hidden_form)

    async def reload(**_kwargs):
        state["reloaded"] = True

    page.locator.side_effect = locator
    page.reload = AsyncMock(side_effect=reload)
    monkeypatch.setattr("backend.app.modules.bot_nuevos_productos.runner.asyncio.sleep", AsyncMock())

    result = asyncio.run(runner._find_utel_form(page, _config("tarjeta")))

    assert result is visible_form
    page.reload.assert_awaited_once_with(wait_until="domcontentloaded", timeout=5)
