from backend.app.config.settings import Settings
from backend.app.automations.utel_inconcert.runner import UtelInconcertRunner
from backend.app.schemas.bot import UtelLead, UtelQaConfig


def _config(destination: str, origin: str = "") -> UtelQaConfig:
    return UtelQaConfig(
        country="Mexico",
        utel_url="https://utel.edu.mx/programa",
        inconcert_url="https://mas-utel.inconcertcc.com/",
        lead_origin_url=origin,
        lead_search_destination=destination,
        modality="En linea",
        level="Licenciatura",
        lead=UtelLead(),
    )


def test_new_products_explicit_lead_destinations(tmp_path):
    runner = UtelInconcertRunner(Settings(storage_dir=tmp_path))

    inconcert = _config("inconcert", "https://lead-balancer.scalahed.com/leads/")
    assert runner._searches_balanceador_only(inconcert) is False
    assert runner._allows_balanceador_fallback(inconcert) is False

    balanceador = _config("balanceador")
    assert runner._searches_balanceador_only(balanceador) is True
    assert runner._allows_balanceador_fallback(balanceador) is False

    both = _config("both")
    assert runner._searches_balanceador_only(both) is False
    assert runner._allows_balanceador_fallback(both) is True


def test_auto_destination_keeps_legacy_excel_behavior(tmp_path):
    runner = UtelInconcertRunner(Settings(storage_dir=tmp_path))
    legacy = _config("auto", "https://lead-balancer.scalahed.com/leads/")
    assert runner._searches_balanceador_only(legacy) is True
    assert runner._allows_balanceador_fallback(legacy) is False
