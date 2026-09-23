from datetime import date

import pytest

from backend.app.modules.bot_nuevos_productos.test_lead_service import TestLeadService


def test_reserves_unique_country_aware_test_leads(tmp_path):
    service = TestLeadService(tmp_path / "leads.db")

    first = service.reserve("México")
    second = service.reserve("México")
    third = service.reserve("Colombia")

    assert first["email"] == f"Testing{date.today().isoformat()}N1@testingUtel.com"
    assert second["email"].endswith("N2@testingUtel.com")
    assert len(first["phone"]) == 10
    assert first["phone"].startswith("55")
    assert len(third["phone"]) == 10
    assert third["phone"].startswith("3")
    assert len({first["email"], second["email"], third["email"]}) == 3
    assert len({first["phone"], second["phone"], third["phone"]}) == 3


def test_real_submission_uses_only_authorized_country_phone(tmp_path):
    service = TestLeadService(
        tmp_path / "authorized.db",
        {
            "México": ["+52 55 1234 5678"],
            "Argentina": ["+54 9 11 2345 6789"],
        },
    )

    mexico, argentina = service.reserve_many(
        ["Mexico", "Argentina"],
        require_authorized_phone=True,
    )

    assert mexico["phone"] == "5512345678"
    # UTEL agrega +54 mediante el selector; el campo recibe los diez dígitos locales.
    assert argentina["phone"] == "1123456789"


def test_real_submission_rejects_missing_or_wrong_country_phone(tmp_path):
    missing = TestLeadService(tmp_path / "missing.db", {})
    with pytest.raises(ValueError, match="falta un banco.*Paraguay"):
        missing.reserve("Paraguay", require_authorized_phone=True)

    wrong_country = TestLeadService(
        tmp_path / "wrong.db",
        {"Mexico": ["+1 202 555 0123"]},
    )
    with pytest.raises(ValueError, match="no es válido para Mexico"):
        wrong_country.reserve("Mexico", require_authorized_phone=True)


def test_authorized_batch_reservation_rolls_back_if_pool_is_insufficient(tmp_path):
    service = TestLeadService(
        tmp_path / "atomic.db",
        {"Mexico": ["+52 55 1234 5678"]},
    )

    with pytest.raises(ValueError, match="se agotaron"):
        service.reserve_many(
            ["Mexico", "Mexico"],
            require_authorized_phone=True,
        )

    # La primera reserva del intento fallido no quedó consumida.
    lead = service.reserve("Mexico", require_authorized_phone=True)
    assert lead["phone"] == "5512345678"


def test_authorized_capacity_validation_does_not_consume_numbers(tmp_path):
    service = TestLeadService(
        tmp_path / "capacity.db",
        {"Mexico": ["+52 55 1234 5678", "+52 55 9876 5432"]},
    )

    service.validate_authorized_capacity(["Mexico", "Mexico"])
    leads = service.reserve_many(
        ["Mexico", "Mexico"],
        require_authorized_phone=True,
    )

    assert [lead["phone"] for lead in leads] == ["5512345678", "5598765432"]


def test_synthetic_real_mode_generates_country_valid_phone(tmp_path):
    service = TestLeadService(
        tmp_path / "synthetic-real.db",
        allow_synthetic_real_phones=True,
    )

    lead = service.reserve("Ecuador", require_authorized_phone=False)

    assert len(lead["phone"]) == 9
    assert lead["phone"].startswith("9")
