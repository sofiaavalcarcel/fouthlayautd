from concurrent.futures import ThreadPoolExecutor
import asyncio
from unittest.mock import AsyncMock, Mock

from backend.app.modules.bot_nuevos_productos.program_rotation_service import ProgramRotationService
from backend.app.modules.bot_nuevos_productos.runner import UtelInconcertRunner
from backend.app.config.settings import Settings
from backend.app.modules.bot_nuevos_productos.schemas import UtelQaConfig, UtelLead


def options(*names):
    return [{"text": name, "value": name} for name in names]


def test_persistent_rotation_and_changed_availability(tmp_path):
    path = tmp_path / "rotation.db"
    scope = ["Mexico", "Maestria", "En linea", "footer", "dry_run"]
    def choose(names):
        return ProgramRotationService(path).choose(scope, options(*names))["text"]
    assert [choose("ABC") for _ in range(3)] == list("ABC")
    assert choose("ABCD") == "D"
    assert choose("BC") == "B"
    assert choose("ABC") == "A"


def test_isolated_scopes_and_single_candidate(tmp_path):
    service = ProgramRotationService(tmp_path / "rotation.db")
    scope = ["Mexico", "Doctorado", "En linea", "tarjeta", "dry_run"]
    assert service.choose(scope, options("A", "B"))["text"] == "A"
    for index, replacement in enumerate(["Peru", "Maestria", "Hibrida", "footer", "real"]):
        other = scope.copy()
        other[index] = replacement
        assert service.choose(other, options("A", "B"))["text"] == "A"
    assert service.choose(scope, options("A", "B"))["text"] == "B"
    assert service.choose(scope, options("A"))["text"] == "A"


def test_parallel_reservations_do_not_repeat(tmp_path):
    service = ProgramRotationService(tmp_path / "rotation.db")
    with ThreadPoolExecutor(max_workers=4) as pool:
        selected = list(pool.map(lambda _: service.choose(["scope"], options("A", "B", "C", "D"))["text"], range(4)))
    assert len(set(selected)) == 4


def test_cards_rotate_and_click_explore(tmp_path):
    cards = Mock()
    cards.first.wait_for = AsyncMock()
    cards.count = AsyncMock(return_value=2)
    targets = []
    card_list = []
    for label in ("Doctorado A", "Doctorado B"):
        card = Mock()
        text = Mock(count=AsyncMock(return_value=1), inner_text=AsyncMock(return_value=label))
        target = Mock(count=AsyncMock(return_value=1), is_visible=AsyncMock(return_value=True),
                      scroll_into_view_if_needed=AsyncMock(), click=AsyncMock())
        card.locator.return_value = Mock(first=text, count=AsyncMock(return_value=0))
        card.get_by_text.return_value.first = target
        targets.append(target)
        card_list.append(card)
    cards.nth.side_effect = lambda index: card_list[index]
    page = Mock(url="https://utel.test/doctorados")
    page.locator.return_value = cards
    config = UtelQaConfig(country="Mexico", level="Doctorado", modality="En linea", form_type="tarjeta",
                          utel_url=page.url, dry_run=True, lead=UtelLead())
    for expected in ("Doctorado A", "Doctorado B"):
        runner = UtelInconcertRunner(Settings(database_path=tmp_path / "rotation.db"))
        runner._rotation_config = config
        asyncio.run(runner._click_first_program_card(page))
        assert runner.selected_program_name == expected
    for target in targets:
        target.click.assert_awaited_once()


def _philippines_master_config(**overrides):
    values = {
        "country": "Filipinas",
        "level": "Master's Degree",
        "navigation_level": "Master",
        "modality": "Online",
        "form_type": "lateral",
        "utel_url": "https://utel.edu.mx/philippines/master-online",
        "dry_run": True,
        "lead": UtelLead(),
    }
    values.update(overrides)
    return UtelQaConfig(**values)


def test_philippines_master_options_rotate_through_the_complete_available_list(tmp_path):
    names = [
        "Master in Business Administration (MBA)",
        "Master in Data Science for Business",
        "Master in Digital Marketing and e-Commerce",
        "Master in Education",
        "Master in Executive Coaching and Organizational Consulting",
        "Master in Innovation Project Management",
    ]
    candidates = options(*names)
    selected = []

    for _ in names:
        runner = UtelInconcertRunner(Settings(database_path=tmp_path / "rotation.db"))
        selected.append(
            runner._rotate_program(candidates, "https://utel.edu.mx/philippines/master-online", _philippines_master_config())["text"]
        )

    assert selected == names
    runner = UtelInconcertRunner(Settings(database_path=tmp_path / "rotation.db"))
    assert runner._rotate_program(
        candidates,
        "https://utel.edu.mx/philippines/master-online",
        _philippines_master_config(),
    )["text"] == names[0]


def test_philippines_master_ignores_generic_page_heading_and_uses_form_rotation(tmp_path):
    runner = UtelInconcertRunner(Settings(database_path=tmp_path / "rotation.db"))
    runner.selected_program_name = "Master's Degree"
    runner._set_dynamic_field = AsyncMock()
    runner._academic_values = AsyncMock(return_value=[])
    runner._select_optional_bachillerato = AsyncMock()
    runner._select_random_city = AsyncMock()
    runner._select_preferred_contact_channel = AsyncMock()
    runner._fill_first_available = AsyncMock()
    runner._set_country_if_possible = AsyncMock()
    runner._check_privacy = AsyncMock()

    async def choose_program(page, form, selector, config):
        assert runner.selected_program_name == ""
        runner.selected_program_name = "Master in Education"

    runner._select_random_program = AsyncMock(side_effect=choose_program)

    asyncio.run(runner._fill_utel_form(Mock(), Mock(), _philippines_master_config()))

    runner._select_random_program.assert_awaited_once()
    product_assignments = [
        call for call in runner._set_dynamic_field.await_args_list
        if call.args[1] == '[data-cy="productsInput"]'
    ]
    assert product_assignments == []
    assert runner.selected_program_name == "Master in Education"


def test_direct_program_recovers_only_when_utel_did_not_preselect_it(tmp_path):
    """Una PDP directa delega al recuperador sin rotar programas al azar."""

    runner = UtelInconcertRunner(Settings(database_path=tmp_path / "rotation.db"))
    runner._set_dynamic_field = AsyncMock()
    runner._academic_values = AsyncMock(return_value=[])
    runner._select_optional_bachillerato = AsyncMock()
    runner._select_random_city = AsyncMock()
    runner._select_preferred_contact_channel = AsyncMock()
    runner._fill_first_available = AsyncMock()
    runner._set_country_if_possible = AsyncMock()
    runner._check_privacy = AsyncMock()
    runner._select_random_program = AsyncMock()
    runner._recover_missing_program_selection = AsyncMock()
    config = _philippines_master_config().model_copy(
        update={"program_name": "Maestría en Arquitectura de Software"}
    )

    page = Mock()
    form = Mock()
    asyncio.run(runner._fill_utel_form(page, form, config))

    runner._recover_missing_program_selection.assert_awaited_once_with(form, config)
    runner._select_random_program.assert_not_awaited()


def test_missing_preselected_program_is_recovered_and_reported(tmp_path):
    """El formulario puede mostrar el programa sin el prefijo Maestría/Carrera."""

    runner = UtelInconcertRunner(Settings(database_path=tmp_path / "rotation.db"))
    field = Mock(
        count=AsyncMock(return_value=1),
        input_value=AsyncMock(side_effect=["", "Ingeniería de Datos e Infraestructura"]),
    )
    field.first = field
    form = Mock()
    form.locator.return_value = field
    runner._set_dynamic_field = AsyncMock()
    config = _philippines_master_config().model_copy(
        update={"program_name": "Maestría en Ingeniería de Datos e Infraestructura"}
    )

    asyncio.run(runner._recover_missing_program_selection(form, config))

    runner._set_dynamic_field.assert_awaited_once_with(
        form,
        '[data-cy="productsInput"]',
        "Maestría en Ingeniería de Datos e Infraestructura",
    )
    assert runner.selected_program_name == "Maestría en Ingeniería de Datos e Infraestructura"
    assert "sin preselección" in runner.program_selection_notice
