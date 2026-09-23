import asyncio
from unittest.mock import AsyncMock

import pytest

from backend.app.automations.utel_inconcert.runner import UtelInconcertRunner, UtelQaError
from backend.app.config.settings import Settings
from backend.app.schemas.bot import UtelQaConfig, UtelLead


@pytest.mark.parametrize("skip", [False, True])
@pytest.mark.parametrize("lost", [False, True])
def test_direct_card_preserves_academic_fields_and_detects_reset(tmp_path, skip, lost):
    runner = UtelInconcertRunner(Settings(storage_dir=tmp_path))
    initial = [{"field": "educationLevelInput", "value": "Licenciatura"},
               {"field": "productsInput", "value": "20261596"}]
    final = [initial[0], {"field": "productsInput", "value": ""}] if lost else initial
    runner._academic_values = AsyncMock(side_effect=[initial, initial, final])
    for name in ("_set_dynamic_field", "_recover_missing_program_selection",
                 "_select_optional_bachillerato", "_select_random_city",
                 "_select_preferred_contact_channel", "_fill_first_available",
                 "_set_country_if_possible", "_check_privacy"):
        setattr(runner, name, AsyncMock())
    config = UtelQaConfig(
        country="Argentina", utel_url="https://utel.edu.mx/argentina/programa",
        level="Licenciatura", modality="En linea", form_type="tarjeta",
        program_name="Licenciatura en Finanzas y Estrategia Fiscal",
        skip_preselected_fields=skip, lead=UtelLead(),
    )
    if lost:
        with pytest.raises(UtelQaError, match="reinicio"):
            asyncio.run(runner._fill_utel_form(None, object(), config))
    else:
        asyncio.run(runner._fill_utel_form(None, object(), config))
    runner._set_dynamic_field.assert_not_awaited()
    runner._recover_missing_program_selection.assert_not_awaited()
    assert runner._fill_first_available.await_count == 3


def test_direct_card_fills_only_missing_program(tmp_path):
    runner = UtelInconcertRunner(Settings(storage_dir=tmp_path))
    initial = [
        {"field": "educationLevelInput", "value": "Licenciatura"},
        {"field": "productsInput", "value": ""},
    ]
    selected = [
        {"field": "educationLevelInput", "value": "Licenciatura"},
        {"field": "productsInput", "value": "20261596"},
    ]
    runner._academic_values = AsyncMock(side_effect=[initial, selected, selected])
    for name in (
        "_set_dynamic_field",
        "_recover_missing_program_selection",
        "_select_optional_bachillerato",
        "_select_random_city",
        "_select_preferred_contact_channel",
        "_fill_first_available",
        "_set_country_if_possible",
        "_check_privacy",
    ):
        setattr(runner, name, AsyncMock())
    config = UtelQaConfig(
        country="Argentina",
        utel_url="https://utel.edu.mx/argentina/programa",
        level="Licenciatura",
        modality="En linea",
        form_type="tarjeta",
        program_name="Licenciatura en Arquitectura",
        lead=UtelLead(),
    )

    form = object()
    asyncio.run(runner._fill_utel_form(None, form, config))

    runner._recover_missing_program_selection.assert_awaited_once_with(
        form, config
    )
    runner._set_dynamic_field.assert_not_awaited()
