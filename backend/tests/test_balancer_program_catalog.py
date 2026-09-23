import asyncio

import pytest

from backend.app.modules.strapi_products.balancer_catalog import (
    BalancerCatalogError,
    BalancerProgramCatalog,
    _is_manual_challenge,
    program_lookup_details,
    select_catalog_code,
)


def test_program_lookup_uses_base_name_and_preserves_degree_for_matching():
    assert program_lookup_details("Licenciatura en Educación para la Sustentabilidad") == (
        "Educación para la Sustentabilidad",
        "licenciatura",
    )
    assert program_lookup_details("Maestría en Educación para la Sustentabilidad") == (
        "Educación para la Sustentabilidad",
        "maestria",
    )
    assert program_lookup_details("Doctorado Educación para la Sustentabilidad") == (
        "Educación para la Sustentabilidad",
        "doctorado",
    )


def test_select_catalog_code_matches_base_name_and_degree():
    rows = [
        ["20261591", "Educación para la Sustentabilidad", "LICENCIATURA"],
        ["20271591", "Educación para la Sustentabilidad", "MASTER"],
        ["20260001", "Educación para otra cosa", "LICENCIATURA"],
    ]
    assert select_catalog_code(rows, "Maestría en Educación para la Sustentabilidad") == "20271591"


def test_select_catalog_code_rejects_ambiguous_matches():
    rows = [
        ["100", "Educación para la Sustentabilidad", "LICENCIATURA"],
        ["101", "Educación para la Sustentabilidad", "LICENCIATURA"],
    ]
    with pytest.raises(BalancerCatalogError, match="varios códigos"):
        select_catalog_code(rows, "Licenciatura en Educación para la Sustentabilidad")


def test_manual_challenge_is_detected_without_attempting_to_bypass_it():
    assert _is_manual_challenge(
        "https://lead-balancer.scalahed.com/login/?__cf_chl_rt_tk=token",
        "Just a moment...",
        "",
    )
    assert not _is_manual_challenge(
        "https://lead-balancer.scalahed.com/catalog/program-of-interest",
        "Catalogo de Programas de interes",
        "Buscar",
    )


def test_manual_challenge_waits_for_user_and_reports_progress():
    class FakeBody:
        def __init__(self, page):
            self.page = page

        async def inner_text(self):
            return self.page.body

    class FakePage:
        url = "https://lead-balancer.scalahed.com/catalog/program-of-interest?__cf_chl=1"

        def __init__(self):
            self.body = "Just a moment... Verify you are human"
            self.fronted = False

        def locator(self, _selector):
            return FakeBody(self)

        async def title(self):
            return "Just a moment..."

        async def bring_to_front(self):
            self.fronted = True

        async def wait_for_function(self, *_args, **_kwargs):
            # Simulate the user resolving Cloudflare in the visible window.
            self.url = "https://lead-balancer.scalahed.com/catalog/program-of-interest"
            self.body = "Catálogo de programas"

    async def run():
        messages = []
        catalog = BalancerProgramCatalog(
            "https://lead-balancer.scalahed.com/leads/",
            progress_callback=messages.append,
        )
        page = FakePage()
        catalog.page = page

        await catalog._wait_for_manual_challenge()

        assert page.fronted
        assert len(messages) == 2
        assert "ventana visible" in messages[0]
        assert "Verificación completada" in messages[1]

    asyncio.run(run())


def test_open_catalog_waits_for_search_without_stale_challenge_method():
    class FakeLocator:
        first = None

        def __init__(self, *, count=0):
            self.count_value = count
            self.first = self

        async def count(self):
            return self.count_value

        async def wait_for(self, **_kwargs):
            return None

        async def inner_text(self):
            return "Programas de interés"

    class FakePage:
        url = ""

        async def goto(self, url, **_kwargs):
            self.url = url

        async def title(self):
            return "Catálogo de programas"

        def locator(self, selector):
            if selector == "body":
                return FakeLocator()
            if selector.startswith("input[type='password']"):
                return FakeLocator(count=0)
            return FakeLocator()

    async def run():
        catalog = BalancerProgramCatalog("https://lead-balancer.scalahed.com/leads/")
        catalog.page = FakePage()

        await catalog._open_catalog()

        assert catalog.page.url.endswith("/catalog/program-of-interest")

    asyncio.run(run())


def test_catalog_search_uses_base_name_and_returns_matching_code():
    class FakeLocator:
        def __init__(self, *, rows=None, value=""):
            self.rows = rows or []
            self.value = value
            self.pressed = None
            self.first = self

        async def get_attribute(self, name):
            return "catalog" if name == "aria-controls" else None

        async def inner_text(self):
            return self.value or "Mostrando 1 a 10 de 365 entradas"

        async def wait_for(self, **kwargs):
            return None

        async def fill(self, value):
            self.value = value

        async def press(self, value):
            self.pressed = value

        async def evaluate_all(self, script):
            return self.rows

    class FakePage:
        url = "https://lead-balancer.scalahed.com/catalog/program-of-interest"

        def __init__(self):
            self.search = FakeLocator()
            self.info = FakeLocator(value="Mostrando 1 a 10 de 365 entradas")
            self.table = FakeLocator(rows=[
                ["20261591", "Educación para la Sustentabilidad", "LICENCIATURA"],
            ])

        def locator(self, selector):
            if selector.startswith("input[type='search']"):
                return self.search
            if selector == "#catalog_info":
                return self.info
            return self.table

        async def wait_for_function(self, _expression, *, arg, **_kwargs):
            self.info.value = "Mostrando 1 a 1 de 1 entradas (Filtrado de 365 total de entradas)"

    async def run():
        catalog = BalancerProgramCatalog("https://lead-balancer.scalahed.com/leads/")
        page = FakePage()
        catalog.page = page
        catalog.start = async_noop
        code = await catalog.get_siu_key("Licenciatura en Educación para la Sustentabilidad")
        assert code == "20261591"
        assert page.search.value == "Educación para la Sustentabilidad"
        assert page.search.pressed == "Enter"

    async def async_noop():
        return None

    asyncio.run(run())
