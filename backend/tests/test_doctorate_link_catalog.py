import asyncio
from unittest.mock import AsyncMock, Mock
from urllib.parse import urlparse

import pytest

from backend.app.modules.bot_nuevos_productos.runner import UtelInconcertRunner, UtelQaError
from backend.app.config.settings import Settings
from backend.app.modules.bot_nuevos_productos.schemas import UtelLead, UtelQaConfig
from backend.app.modules.bot_nuevos_productos.doctorate_link_catalog import DoctorateLinkCatalog


def _config(country: str = "Bolivia", **overrides) -> UtelQaConfig:
    values = {
        "country": country,
        "utel_url": f"https://utel.edu.mx/{country.lower()}/doctorados",
        "modality": "En linea",
        "level": "Doctorado",
        "form_type": "tarjeta",
        "workflow_mode": "form_validation",
        "lead": UtelLead(),
    }
    values.update(overrides)
    return UtelQaConfig(**values)


def _settings(tmp_path) -> Settings:
    return Settings(database_path=tmp_path / "qa.db", storage_dir=tmp_path / "storage")


def test_catalog_includes_administration_as_a_form_option_on_education_pdp():
    countries = [
        "USA",
        "Bolivia",
        "Chile",
        "Paraguay",
        "Dominicana",
        "Guatemala",
        "Panama",
        "El Salvador",
        "Argentina",
        "Mexico",
        "Colombia",
        "Peru",
    ]
    counts = {country: len(DoctorateLinkCatalog.programs(country)) for country in countries}

    assert sum(counts.values()) == 78
    assert counts["Dominicana"] == 4
    assert counts["Mexico"] == 21
    assert counts["Colombia"] == 20
    assert counts["Peru"] == 17
    assert all(
        count == 2
        for country, count in counts.items()
        if country not in {"Dominicana", "Mexico", "Colombia", "Peru"}
    )


def test_administration_strategic_business_is_available_in_every_country():
    countries = [
        "USA", "Bolivia", "Chile", "Paraguay", "Dominicana", "Guatemala",
        "Panama", "El Salvador", "Argentina", "Mexico", "Colombia", "Peru",
    ]

    assert all(
        DoctorateLinkCatalog.resolve(country, "administracion estrategica empresarial") is not None
        for country in countries
    )


def test_administration_uses_education_page_without_opening_its_own_pdp():
    selected = DoctorateLinkCatalog.resolve("Mexico", "administracion estrategica empresarial")

    assert selected is not None
    assert selected["url"] == "https://utel.edu.mx/doctorado-en-educacion"
    assert selected["page_title"] == "Doctorado en Educación"


@pytest.mark.parametrize(
    "filename",
    ["LEADS DEPLOY.xlsx", "Leads Deploy.xlsx", "leads deploy.xlsx", "leads deploy (1).xlsx"],
)
def test_leads_deploy_filename_is_case_insensitive(filename):
    assert DoctorateLinkCatalog.is_leads_deploy_file(filename) is True


def test_unrelated_filename_does_not_activate_leads_deploy_rule():
    assert DoctorateLinkCatalog.is_leads_deploy_file("programas_doctorado.xlsx") is False


@pytest.mark.parametrize(
    ("alias", "path"),
    [
        ("Estados Unidos", "/usa/"),
        ("República Dominicana", "/dominicana/"),
        ("Panamá", "/panama/"),
        ("México", "/doctorado-"),
        ("Perú", "/doctorado-"),
    ],
)
def test_country_aliases_resolve_to_the_expected_catalog(alias, path):
    assert path in DoctorateLinkCatalog.programs(alias)[0]["url"]


def test_exact_program_accepts_the_short_form():
    selected = DoctorateLinkCatalog.resolve("Dominicana", "Finanzas")

    assert selected == {
        "text": "Doctorado en Finanzas",
        "url": "https://utel.edu.mx/dominicana/doctorado-en-finanzas",
    }


@pytest.mark.parametrize(
    ("country", "host", "path_prefix"),
    [
        ("Mexico", "utel.edu.mx", "/doctorado-en-"),
        ("Colombia", "utel.edu.mx", "/colombia/doctorado-en-"),
        ("Peru", "utlenlinea.com", "/doctorado-en-"),
    ],
)
def test_new_country_links_use_the_exact_host_and_route(country, host, path_prefix):
    for program in DoctorateLinkCatalog.programs(country):
        parsed = urlparse(program["url"])

        assert parsed.netloc == host
        assert parsed.path.startswith(path_prefix)
        assert parsed.query == ""


def test_direct_programs_rotate_persistently_by_country(tmp_path):
    settings = _settings(tmp_path)
    first_runner = UtelInconcertRunner(settings)
    second_runner = UtelInconcertRunner(settings)

    first = first_runner._select_direct_doctorate_program(_config(country="Mexico"))
    second = second_runner._select_direct_doctorate_program(_config(country="Mexico"))

    assert first["text"] == "Doctorado en Estudios Interdisciplinarios sobre América Latina"
    assert second["text"] == "Doctorado en Estudios Interculturales y Diversidad Humana"
    assert first["url"] != second["url"]


def test_open_utel_uses_the_direct_url_and_validates_the_h1(tmp_path):
    runner = UtelInconcertRunner(_settings(tmp_path))
    page = Mock(url="https://utel.edu.mx")
    page.goto = AsyncMock()
    body = AsyncMock()
    body.inner_text.return_value = "Página de programa UTEL"
    heading = AsyncMock()
    heading.first = heading
    heading.inner_text.return_value = "Doctorado en Educación"
    page.locator.side_effect = lambda selector: body if selector == "body" else heading

    asyncio.run(runner._open_utel(page, _config()))

    page.goto.assert_awaited_once_with(
        "https://utel.edu.mx/bolivia/doctorado-en-educacion",
        wait_until="domcontentloaded",
    )
    heading.wait_for.assert_awaited_once_with(state="visible", timeout=12000)
    assert runner.selected_program_name == "Doctorado en Educación"


def test_direct_pdp_skips_the_program_card_click(tmp_path):
    runner = UtelInconcertRunner(_settings(tmp_path))
    runner._selected_direct_url = "https://utel.edu.mx/bolivia/doctorado-en-educacion"
    runner._navigate_form_validation = AsyncMock()

    asyncio.run(runner._navigate_utel(AsyncMock(), _config()))

    runner._navigate_form_validation.assert_not_awaited()


def test_leads_deploy_ignores_the_row_url_for_every_doctorate_form_location(tmp_path):
    runner = UtelInconcertRunner(_settings(tmp_path))

    selected = runner._select_direct_doctorate_program(
        _config(
            form_type="footer",
            source_filename="Leads Deploy.xlsx",
            utel_url="https://example.test/url-general-que-debe-ignorarse",
        )
    )

    assert selected is not None
    assert selected["url"].startswith("https://utel.edu.mx/bolivia/doctorado-")
    assert "example.test" not in selected["url"]


def test_leads_deploy_fails_clearly_when_country_is_missing_from_direct_catalog(tmp_path):
    runner = UtelInconcertRunner(_settings(tmp_path))

    with pytest.raises(UtelQaError, match="no contiene enlaces para Ecuador") as caught:
        runner._select_direct_doctorate_program(
            _config(country="Ecuador", source_filename="LEADS DEPLOY.xlsx")
        )

    assert caught.value.stage == "utel_navigation"


@pytest.mark.parametrize(
    "overrides",
    [
        {"form_type": "footer"},
        {"level": "Maestría"},
        {"workflow_mode": "product_release"},
    ],
)
def test_catalog_does_not_change_other_workflows(tmp_path, overrides):
    runner = UtelInconcertRunner(_settings(tmp_path))

    assert runner._select_direct_doctorate_program(_config(**overrides)) is None


def test_unknown_exact_program_fails_before_opening_a_wrong_pdp(tmp_path):
    runner = UtelInconcertRunner(_settings(tmp_path))

    with pytest.raises(UtelQaError, match="no existe en el catálogo directo") as caught:
        runner._select_direct_doctorate_program(_config(program_name="Doctorado inexistente"))

    assert caught.value.stage == "utel_navigation"
