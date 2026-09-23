from io import BytesIO

from openpyxl import Workbook
import pytest

from backend.app.modules.bot_nuevos_productos.spreadsheet_service import BotSpreadsheetService


@pytest.mark.parametrize("country,tenant", [
    ("Mexico", "mas-utel"), (" México ", "mas-utel"),
    ("Argentina", "mas-utel-arg"), ("Colombia", "mas-utel-col"),
    ("peru", "mas-utel-pe"), ("Perú", "mas-utel-pe"),
    ("ecuador", "mas-utel-ec"),
])
def test_country_inconcert_urls(country, tenant):
    assert BotSpreadsheetService.default_inconcert_url(country) == (
        f"https://{tenant}.inconcertcc.com/login?redirect=%2Fmas%2Fhome"
    )


def test_previously_configured_countries_are_preserved():
    service = BotSpreadsheetService()
    assert "mas-utel-bol." in service.default_inconcert_url("Bolivia")
    assert "mas-utel-dom." in service.default_inconcert_url("República Dominicana")
    assert "mas-utel-singapur." in service.default_inconcert_url("Filipinas")
    for country in ("USA", "Chile", "Paraguay", "Guatemala", "Panamá", "El Salvador"):
        assert "mas-utel-emergentes." in service.default_inconcert_url(country)
    assert service.default_inconcert_url("Sin configurar") == ""


def test_supports_level_location_locale_and_inconcert_columns():
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Country", "Nivel", "URL", "Location", "Locale", "Cliente", "inconcert/balanceador"])
    sheet.append(["M\u00e9xico", "Maestr\u00eda", "https://utel.test/mexico", "footer", "M\u00e9xico", "QA", "https://crm.test"])
    content = BytesIO()
    workbook.save(content)

    rows = BotSpreadsheetService().rows_for_mapping(
        content.getvalue(),
        {
            "country": "Locale",
            "level": "Nivel",
            "utel_url": "URL",
            "form_type": "Location",
            "inconcert_url": "inconcert/balanceador",
        },
    )

    assert rows == [{
        "sheet": "Sheet", "row_number": 2, "program_name": "", "modality": "",
        "level": "Maestr\u00eda", "country": "M\u00e9xico", "form_type": "footer",
        "inconcert_url": "https://crm.test", "lead_origin_url": "", "utel_url": "https://utel.test/mexico",
        "workflow_mode": "form_validation", "test_case": "Maestr\u00eda",
    }]


def test_builds_navigation_plans_for_deploy_levels():
    service = BotSpreadsheetService()
    assert service.deploy_navigation_plan("Licenciatura Ejecutiva", "Mexico") == {
        "modality": "Ejecutiva", "level": "Licenciatura",
        "navigation_modality": "Modalidad ejecutiva", "navigation_level": "Licenciaturas",
        "navigation_sublevel": "",
    }
    assert service.deploy_navigation_plan("Maestr\u00eda Hibrida", "Mexico")["navigation_modality"] == "Modalidad hibrida"
    assert service.deploy_navigation_plan("Filipinas Master", "Global")["navigation_level"] == "Master"
    assert service.deploy_navigation_plan("Filipinas Master", "Global")["level"] == "Master's Degree"
    assert service.deploy_navigation_plan("India Bachelor", "Global")["level"] == "Bachelor's Degree"


def test_supports_lead_origin_and_official_catalog_urls():
    workbook = Workbook()
    workbook.active.append(["Nivel", "URL", "Location", "Locale", "Url Origen Lead"])
    workbook.active.append([
        "Bachelor", "https://utel.edu.mx/indonesia", "Footer", "Indonesia",
        "https://lead-balancer.scalahed.com",
    ])
    content = BytesIO()
    workbook.save(content)

    rows = BotSpreadsheetService().rows_for_mapping(
        content.getvalue(),
        {
            "level": "Nivel", "utel_url": "URL", "form_type": "Location",
            "country": "Locale", "lead_origin_url": "Url Origen Lead",
        },
    )
    assert rows[0]["lead_origin_url"] == "https://lead-balancer.scalahed.com"
    catalog = BotSpreadsheetService().catalog_programs("Indonesia", "Bachelor", "Online")
    assert catalog[0]["url"].startswith("https://utel.edu.mx/indonesia/")
