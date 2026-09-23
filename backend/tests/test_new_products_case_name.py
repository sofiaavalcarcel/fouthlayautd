from backend.app.api.routes import (
    _new_products_case_name,
    _new_products_retry_browser,
)


def test_new_products_case_name_preserves_short_names():
    assert _new_products_case_name("Bot", "Programa") == "Bot - Programa"


def test_new_products_case_name_limits_long_programs_to_schema_maximum():
    result = _new_products_case_name(
        "Bot nuevos productos - pendientes solo Balanceador",
        "Licenciatura en Inteligencia Artificial Aplicada a Negocios, Industria y Automatización",
    )

    assert len(result) == 120
    assert result.endswith("...")
    assert result.startswith("Bot nuevos productos")


def test_new_products_access_block_retries_with_a_different_browser():
    result = {
        "summary": "El sitio bloqueó el acceso de esta sesion. No se envió el formulario.",
        "stages": [],
    }

    assert (
        _new_products_retry_browser(result, is_leads_deploy=False)
        == "chromium"
    )
    assert _new_products_retry_browser(result, is_leads_deploy=True) == "chrome"
