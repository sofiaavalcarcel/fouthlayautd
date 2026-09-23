from backend.app.modules.bot_nuevos_productos.runner import UtelInconcertRunner
from backend.app.config.settings import Settings


def test_education_menu_accepts_country_specific_level_names():
    runner = UtelInconcertRunner(Settings())

    bachelor = runner._education_level_candidates("Licenciaturas")
    masters = runner._education_level_candidates("Maestrias")

    assert "Carrera" in bachelor
    assert "Carreras" in bachelor
    assert "Mag\u00edster" in masters
    assert "Mag\u00edsteres" in masters


def test_form_level_accepts_carrera_and_magister_aliases():
    runner = UtelInconcertRunner(Settings())

    assert "Carreras" in runner._level_candidates("Licenciatura")
    assert "Mag\u00edsteres" in runner._level_candidates("Maestria")
