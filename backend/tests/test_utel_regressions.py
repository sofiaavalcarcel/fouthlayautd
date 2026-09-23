import asyncio
import re
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, Mock

import pytest

from backend.app.modules.bot_nuevos_productos.runner import (
    PostSubmitSignal,
    RejectedSubmission,
    UnconfirmedSubmission,
    UtelInconcertRunner,
    UtelQaError,
    UtelRunCancelled,
)
from backend.app.modules.bot_nuevos_productos.router import _is_support_rejection, _is_temporary_access_block
from backend.app.config.settings import Settings
from backend.app.modules.bot_nuevos_productos.schemas import UtelLead, UtelQaConfig
from backend.app.modules.bot_nuevos_productos.test_lead_service import TestLeadService
from backend.app.modules.bot_nuevos_productos.spreadsheet_service import BotSpreadsheetService


def test_global_country_requires_explicit_philippines_context():
    service = BotSpreadsheetService()
    assert service.effective_country("Global", "Filipinas Bachelor", "https://utel.edu.mx") == "Filipinas"
    assert service.effective_country("Global", "Bachelor", "https://utel.edu.mx/philippines/") == "Filipinas"
    assert service.effective_country("Global", "Bachelor", "https://utel.edu.mx") == "Global"
    assert "singapur" in service.default_inconcert_url("Filipinas")


@pytest.mark.parametrize("message,error", [
    ("Successfully submitted\nYour information has been received", None),
    ("Gracias, hemos recibido tu solicitud. Te contactaremos pronto.", None),
    ("Error al enviar. Contacta a soporte", RejectedSubmission),
    ("Mensaje desconocido", UnconfirmedSubmission),
])
def test_toast_with_saved_spanish_pattern(message, error):
    runner = UtelInconcertRunner(Settings())
    runner._last_submit_success_pattern = "envio correcto"
    runner._validate_utel_form_before_submit = AsyncMock()
    submit = AsyncMock()
    submit.is_enabled.return_value = True
    form = Mock()
    form.locator.return_value.first = submit
    toast = AsyncMock()
    toast.inner_text.return_value = message
    page = Mock(wait_for_function=AsyncMock())
    page.locator.return_value = toast
    if error:
        with pytest.raises(error):
            asyncio.run(runner._submit_utel_form(page, form))
    else:
        asyncio.run(runner._submit_utel_form(page, form))
    submit.evaluate.assert_awaited_once()


def test_explicit_error_toast_is_a_reconcilable_post_submit_signal():
    """Un rechazo visual ocurre despues del unico clic y debe conciliarse en CRM."""

    runner = UtelInconcertRunner(Settings())
    runner._validate_utel_form_before_submit = AsyncMock()
    submit = AsyncMock()
    submit.is_enabled.return_value = True
    form = Mock()
    form.locator.return_value.first = submit
    feedback = Mock(json_value=AsyncMock(return_value="Error al enviar. Contacta a soporte"))
    page = Mock(wait_for_function=AsyncMock(return_value=feedback))

    with pytest.raises(RejectedSubmission) as caught:
        asyncio.run(runner._submit_utel_form(page, form))

    assert isinstance(caught.value, PostSubmitSignal)
    assert caught.value.stage == "utel_submit"
    assert "Error al enviar" in str(caught.value)
    submit.evaluate.assert_awaited_once_with("(element) => element.click()")


def test_invalid_submit_pattern_fails_before_any_click():
    """Las expresiones configurables se compilan durante la validación previa."""

    runner = UtelInconcertRunner(Settings())
    config = UtelQaConfig(
        country="Mexico",
        utel_url="https://utel.test",
        modality="En linea",
        level="Licenciatura",
        submit_error_pattern="(",
        lead=UtelLead(),
    )

    with pytest.raises(UtelQaError) as caught:
        runner._validate_config(config)

    assert caught.value.stage == "config"
    assert "expresión regular válida" in str(caught.value)
    assert runner._submission_attempted is False


def test_unexpected_post_click_error_is_reconciled_instead_of_retried():
    """Incluso un error interno posterior al clic debe producir señal conciliable."""

    runner = UtelInconcertRunner(Settings())
    runner._last_submit_error_pattern = "("
    runner._validate_utel_form_before_submit = AsyncMock()
    submit = AsyncMock()
    submit.is_enabled.return_value = True
    form = Mock()
    form.locator.return_value.first = submit
    feedback = Mock(json_value=AsyncMock(return_value="Error al enviar"))
    page = Mock(wait_for_function=AsyncMock(return_value=feedback))

    with pytest.raises(UnconfirmedSubmission) as caught:
        asyncio.run(runner._submit_utel_form(page, form))

    assert "sin reenviar" in str(caught.value)
    assert runner._submission_attempted is True
    submit.evaluate.assert_awaited_once_with("(element) => element.click()")


def test_support_rejection_is_the_only_post_click_error_eligible_for_retry():
    rejected = {
        "status": "FAIL",
        "lead_url": None,
        "utel_submission_message": "UTEL mostró: Error al enviar. Contacta a soporte",
        "stages": [],
    }
    unconfirmed = {
        **rejected,
        "utel_submission_message": "Envío no confirmado; se verificará en CRM.",
    }
    already_created = {**rejected, "lead_url": "https://crm.test/leads/1"}

    assert _is_support_rejection(rejected)
    assert not _is_support_rejection(unconfirmed)
    assert not _is_support_rejection(already_created)


def test_only_temporary_access_blocks_are_queued_for_end_retry():
    cloudflare = {
        "status": "FAIL",
        "summary": "No se pudo completar la verificación.",
        "stages": [{
            "status": "FAIL",
            "message": "El Balanceador bloqueo esta sesion del navegador antes del login. Cloudflare.",
        }],
    }
    missing_program = {
        "status": "FAIL",
        "summary": "El formulario no tiene una opción equivalente al programa.",
        "stages": [],
    }

    assert _is_temporary_access_block(cloudflare)
    assert not _is_temporary_access_block(missing_program)


def test_form_validation_retries_when_utel_rebuilds_the_dom():
    runner = UtelInconcertRunner(Settings())
    controls = AsyncMock()
    controls.evaluate_all.side_effect = [RuntimeError("DOM reemplazado"), []]
    form = Mock()
    form.locator.return_value = controls

    asyncio.run(runner._validate_utel_form_before_submit(form))

    assert controls.evaluate_all.await_count == 2


def test_balancer_reuses_logged_profile_and_searches_exact_email_without_credentials():
    """Una sesión activa entra en /leads/ y no vuelve a pedir el login."""

    runner = UtelInconcertRunner(Settings(
        lead_balancer_url="https://lead-balancer.scalahed.com/login/",
        lead_balancer_username="",
        lead_balancer_password="",
    ))
    email = "qa-session@testingUtel.com"
    page = Mock(url="")
    response = Mock(status=200)

    async def goto(url, **_kwargs):
        page.url = url if "/detail/" in url else "https://lead-balancer.scalahed.com/leads/"
        return response

    page.goto = AsyncMock(side_effect=goto)
    page.wait_for_url = AsyncMock()
    password = Mock(count=AsyncMock(return_value=0))
    email_input = Mock(count=AsyncMock(return_value=1), fill=AsyncMock())
    email_input.first = email_input
    search_button = Mock(click=AsyncMock())
    search_button.first = search_button
    async def open_detail():
        page.url = "https://lead-balancer.scalahed.com/leads/detail/123"

    detail_link = Mock(
        count=AsyncMock(return_value=1),
        get_attribute=AsyncMock(side_effect=["/leads/detail/123", None]),
        click=AsyncMock(side_effect=open_detail),
    )
    detail_link.first = detail_link
    row = Mock(inner_text=AsyncMock(return_value=f"Lead de prueba {email}"))
    row.locator.return_value = detail_link
    # La tabla tarda dos ciclos de observación en aparecer. El bot debe esperar
    # sin volver a pulsar Buscar y reconocerla apenas se renderice.
    rows = Mock(count=AsyncMock(side_effect=[0, 0, 1]))
    rows.nth.return_value = row
    body = Mock(inner_text=AsyncMock(return_value=email))

    def locator(selector):
        if selector == "input[type='password']:visible":
            return password
        if selector == "table tbody tr:visible":
            return rows
        if selector == "body":
            return body
        return Mock(count=AsyncMock(return_value=0))

    page.locator.side_effect = locator
    page.get_by_label.return_value = email_input
    page.get_by_role.return_value = search_button

    asyncio.run(runner._search_lead_balancer(page, email, "QA Session"))

    assert page.goto.await_args_list[0].args[0] == "https://lead-balancer.scalahed.com/leads/"
    email_input.fill.assert_awaited_once_with(email)
    search_button.click.assert_awaited_once()
    assert runner.lead_url == "https://lead-balancer.scalahed.com/leads/detail/123"


def test_balancer_opens_green_action_when_email_wraps_inside_the_row():
    """Un salto visual dentro del email no debe provocar clics repetidos en Buscar."""

    runner = UtelInconcertRunner(Settings(
        lead_balancer_url="https://lead-balancer.scalahed.com/leads/",
    ))
    email = "Testing2026-09-03N37@testingUtel.com"
    page = Mock(url="")
    response = Mock(status=200)

    async def goto(url, **_kwargs):
        page.url = url
        return response

    page.goto = AsyncMock(side_effect=goto)
    page.wait_for_url = AsyncMock()
    password = Mock(count=AsyncMock(return_value=0))
    email_input = Mock(count=AsyncMock(return_value=1), fill=AsyncMock())
    email_input.first = email_input
    search_button = Mock(click=AsyncMock())
    search_button.first = search_button
    async def open_detail():
        page.url = "https://lead-balancer.scalahed.com/leads/3141175"

    green_action = Mock(
        count=AsyncMock(return_value=1),
        get_attribute=AsyncMock(side_effect=["/leads/3141175", None]),
        click=AsyncMock(side_effect=open_detail),
    )
    green_action.first = green_action
    row = Mock(
        inner_text=AsyncMock(
            return_value="3141175 Danilo Prueba IQ Testing2026-09-\n03N37@testingUtel.com Ecuador"
        )
    )
    row.locator.return_value = green_action
    rows = Mock(count=AsyncMock(return_value=1))
    rows.nth.return_value = row
    body = Mock(inner_text=AsyncMock(return_value="Email: Testing2026-09-\n03N37@testingUtel.com"))

    def locator(selector):
        if selector == "input[type='password']:visible":
            return password
        if selector == "table tbody tr:visible":
            return rows
        if selector == "body":
            return body
        return Mock(count=AsyncMock(return_value=0))

    page.locator.side_effect = locator
    page.get_by_label.return_value = email_input
    page.get_by_role.return_value = search_button

    asyncio.run(runner._search_lead_balancer(page, email, "Danilo Prueba IQ"))

    search_button.click.assert_awaited_once()
    green_action.click.assert_awaited_once()
    assert runner.lead_url == "https://lead-balancer.scalahed.com/leads/3141175"


def test_cooperative_stop_during_validation_prevents_the_click():
    """La ejecución individual todavía puede detenerse hasta el último límite seguro."""

    runner = UtelInconcertRunner(Settings())
    runner._validate_utel_form_before_submit = AsyncMock()
    submit = AsyncMock()
    submit.is_enabled.return_value = True
    form = Mock()
    form.locator.return_value.first = submit
    page = Mock()

    with pytest.raises(UtelRunCancelled):
        asyncio.run(runner._submit_utel_form(page, form, lambda: True))

    assert runner._submission_attempted is False
    submit.evaluate.assert_not_awaited()


def test_crm_preflight_opens_login_and_contacts_without_submitting(tmp_path):
    """El preflight comprueba el CRM real con los flags internos desactivados."""

    runner = UtelInconcertRunner(
        Settings(
            storage_dir=tmp_path,
            inconcert_username="test",
            inconcert_password="test",
        )
    )
    page = Mock(set_default_timeout=Mock())
    context = Mock(new_page=AsyncMock(return_value=page), close=AsyncMock())
    browser = Mock(new_context=AsyncMock(return_value=context), close=AsyncMock())
    playwright = Mock()
    playwright.chromium.launch = AsyncMock(return_value=browser)

    @asynccontextmanager
    async def runtime(*args):
        yield playwright

    runner._playwright = runtime
    runner._close_open_session = AsyncMock()
    runner._open_inconcert = AsyncMock()
    runner._login_inconcert = AsyncMock()
    runner._open_contacts = AsyncMock()
    config = UtelQaConfig(
        country="Mexico",
        utel_url="https://utel.test",
        inconcert_url="https://crm.test/login",
        modality="En linea",
        level="Licenciatura",
        dry_run=False,
        defer_crm_verification=True,
        verification_only=True,
        keep_browser_open=True,
        lead=UtelLead(),
    )

    asyncio.run(runner.preflight_inconcert(config))

    checked_config = runner._open_inconcert.await_args.args[1]
    assert checked_config.defer_crm_verification is False
    assert checked_config.verification_only is False
    assert checked_config.keep_browser_open is False
    runner._login_inconcert.assert_awaited_once_with(page)
    runner._open_contacts.assert_awaited_once_with(page)
    context.close.assert_awaited_once()
    browser.close.assert_awaited_once()


def test_blocked_heading_is_not_a_program():
    runner = UtelInconcertRunner(Settings())
    page = Mock()
    page.locator.return_value.inner_text = AsyncMock(return_value="Sorry, you have been blocked")
    with pytest.raises(UtelQaError) as caught:
        asyncio.run(runner._capture_selected_program(page))
    assert caught.value.stage == "utel_access"
    assert runner.selected_program_name == ""


def test_geographic_fields_only():
    runner = UtelInconcertRunner(Settings())
    fields = [AsyncMock() for _ in range(3)]
    for field, metadata in zip(fields, ["educationLevelInput Area de interes", "province Selecciona una provincia", "city Ciudad:"]):
        field.is_visible.return_value = True
        field.is_enabled.return_value = True
        field.evaluate.return_value = metadata
    form = Mock()
    form.locator.return_value.count = AsyncMock(return_value=3)
    form.locator.return_value.nth.side_effect = fields
    runner._select_random_select_option = AsyncMock()
    asyncio.run(runner._select_random_city(form))
    assert [call.args[0] for call in runner._select_random_select_option.await_args_list] == fields[1:]


def test_phone_prefix_survives_global_sequence_and_pool_exhaustion(tmp_path):
    service = TestLeadService(tmp_path / "leads.db")
    for _ in range(105):
        service.reserve("Mexico")
    numbers = {service.reserve("USA")["phone"] for _ in range(100)}
    assert len(numbers) == 100
    assert all(number.startswith("20255501") and len(number) == 10 for number in numbers)
    with pytest.raises(ValueError, match="agotaron"):
        service.reserve("United States")
    assert service.reserve("Dominicana")["phone"].startswith("80955501")


def test_generated_leads_use_alphabetic_names_and_valid_country_shapes(tmp_path):
    """Evita el rechazo local de Panamá y las series inválidas de AR/PY."""

    service = TestLeadService(tmp_path / "country-shapes.db")
    argentina = service.reserve("Argentina")
    paraguay = service.reserve("Paraguay")
    panama = service.reserve("Panama")

    assert re.fullmatch(r"[A-Za-z]+(?: [A-Za-z]+)+", panama["name"])
    assert not any(character.isdigit() for character in panama["name"])
    assert argentina["phone"].startswith("11") and len(argentina["phone"]) == 10
    assert paraguay["phone"].startswith("981") and len(paraguay["phone"]) == 9


def test_country_is_selected_by_option_name_and_verified():
    """countryCallingCode contiene países; no etiquetas como +54 o +595."""

    runner = UtelInconcertRunner(Settings())
    field = Mock()
    field.count = AsyncMock(return_value=1)
    field.evaluate = AsyncMock(return_value="select")
    field.input_value = AsyncMock(side_effect=["Mexico (México)", "Argentina"])
    field.is_disabled = AsyncMock(return_value=False)
    field.select_option = AsyncMock()
    options = Mock()
    options.evaluate_all = AsyncMock(
        return_value=[
            {"text": "Mexico (México)", "value": "Mexico (México)"},
            {"text": "Argentina", "value": "Argentina"},
        ]
    )
    field.locator.return_value = options
    holder = Mock(first=field)
    form = Mock()
    form.locator.return_value = holder

    asyncio.run(runner._set_country_if_possible(form, "Argentina"))

    field.select_option.assert_awaited_once_with(value="Argentina")


def test_country_waits_for_options_and_rejects_ambiguous_substrings():
    """Una carga tardía no debe convertir India en otro territorio."""

    runner = UtelInconcertRunner(Settings())
    field = Mock()
    field.count = AsyncMock(return_value=1)
    field.evaluate = AsyncMock(return_value="select")
    field.input_value = AsyncMock(return_value="India")
    field.select_option = AsyncMock()
    options = Mock()
    options.evaluate_all = AsyncMock(
        side_effect=[
            [],
            [
                {"text": "British Indian Ocean Territory", "value": "British Indian Ocean Territory"},
                {"text": "India", "value": "India"},
            ],
        ]
    )
    field.locator.return_value = options
    form = Mock()
    form.locator.return_value = Mock(first=field)

    asyncio.run(runner._set_country_if_possible(form, "India"))

    assert options.evaluate_all.await_count == 2
    field.select_option.assert_not_awaited()
    assert runner._country_option_matches("india", "British Indian Ocean Territory") is False
    assert runner._country_option_matches("mexico", "Mexico (México)") is True


def test_api_error_diagnostic_hides_lead_data():
    runner = UtelInconcertRunner(Settings())
    response = Mock(status=422)
    response.text = AsyncMock(
        return_value="Email Testing1@testingUtel.com y telefono +595 981 123 456 rechazados"
    )

    with pytest.raises(RejectedSubmission) as caught:
        asyncio.run(runner._classify_utel_api_response(response))

    message = str(caught.value)
    assert "HTTP 422" in message
    assert "Testing1@testingUtel.com" not in message
    assert "981 123 456" not in message
