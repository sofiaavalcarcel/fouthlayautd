"""Regresión del formulario inferior sin id publicado por UTEL Colombia."""

import asyncio
from unittest.mock import AsyncMock

from playwright.async_api import async_playwright

from backend.app.automations.leads_deploy.runner import LeadsDeployRunner
from backend.app.config.settings import Settings
from backend.app.schemas.bot import UtelQaConfig, UtelLead


def test_asian_footer_opens_home_and_preserves_catalog_program():
    async def scenario():
        runner = LeadsDeployRunner(Settings())
        runner._maximize_visible_browser = AsyncMock()
        runner._check_access = AsyncMock()
        runner._validate_program_heading = AsyncMock()
        page = AsyncMock()
        config = UtelQaConfig(country="Indonesia", level="Master's Degree", modality="Online",
                              form_type="footer", utel_url="https://utel.edu.mx/indonesia/master-in-education",
                              program_name="Master in Education", lead=UtelLead())
        await runner._open_utel(page, config)
        await runner._navigate_utel(page, config)
        page.goto.assert_awaited_once_with("https://utel.edu.mx/indonesia", wait_until="domcontentloaded")
        runner._validate_program_heading.assert_not_awaited()
        assert config.program_name == "Master in Education"
        assert not runner._uses_home_footer(config.model_copy(update={"form_type": "lateral"}))
        assert not runner._uses_home_footer(config.model_copy(update={"country": "Ecuador"}))
        for country in ("Filipinas", "Philippines"):
            page.goto.reset_mock()
            await runner._open_utel(page, config.model_copy(update={"country": country}))
            page.goto.assert_awaited_once_with("https://utel.edu.mx/philippines", wait_until="domcontentloaded")
    asyncio.run(scenario())


def test_footer_without_id_is_located_and_requeried_after_remount():
    async def scenario():
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(channel="chrome", headless=True)
            try:
                page = await browser.new_page(viewport={"width": 1440, "height": 900})
                await page.route("https://example.com/**", lambda route: route.fulfill(body="<html></html>", content_type="text/html"))
                await page.goto("https://example.com/colombia/programa")
                fields = '<input data-cy="emailInput"><input data-cy="telephoneInput"><select data-cy="productsInput"><option>Programa</option></select>'
                for identifier in ('', 'id="FooterBLC"'):
                    await page.set_content(
                        '<header style="position:fixed;top:0;height:100px">Menú</header>'
                        f'<form id="TarjetaBLC">{fields}</form><form id="LateralBLC" hidden>{fields}</form>'
                        '<div style="height:1600px"></div>'
                        f'<div class="form-container-config-chakra-config"><form {identifier} style="height:400px">{fields}</form></div>'
                        '<div style="height:1800px">Preguntas frecuentes y pie legal</div>'
                    )
                    runner = LeadsDeployRunner(Settings())
                    config = UtelQaConfig(country="Colombia", level="Licenciatura", modality="En linea", form_type="footer", utel_url=page.url, lead=UtelLead())
                    form = await runner._find_utel_form(page, config)
                    box = await form.bounding_box()
                    assert box and box["y"] >= 100
                    assert box["y"] + box["height"] <= 900
                    assert await form.get_attribute("id") not in {"TarjetaBLC", "LateralBLC"}
                    # El locator debe sobrevivir al reemplazo del nodo React.
                    await form.evaluate("element => element.replaceWith(element.cloneNode(true))")
                    await runner._footer_locator(page).locator('[data-cy="emailInput"]').fill("qa@example.com")
                    assert await runner._footer_locator(page).locator('[data-cy="emailInput"]').input_value() == "qa@example.com"
                    assert await page.locator('#TarjetaBLC [data-cy="emailInput"]').input_value() == ""
            finally:
                await browser.close()

    asyncio.run(scenario())


def test_program_heading_tolerates_safe_singular_plural_difference():
    assert LeadsDeployRunner._program_titles_equivalent(
        "bootcamp fundamento de ciencias de datos proyectos agiles con scrum",
        "bootcamp fundamentos de ciencias de datos proyectos agiles con scrum",
    )
    assert not LeadsDeployRunner._program_titles_equivalent(
        "bootcamp fundamento de ciencias de datos",
        "bootcamp fundamento de ciencias computacionales",
    )


def test_program_heading_tolerates_same_words_in_editorial_order():
    assert LeadsDeployRunner._program_titles_equivalent(
        "maestria en mindfulness conciencia plena aplicada",
        "conciencia plena aplicada mindfulness",
    )
    assert not LeadsDeployRunner._program_titles_equivalent(
        "maestria en mindfulness conciencia plena aplicada",
        "maestria en educacion y docencia",
    )
