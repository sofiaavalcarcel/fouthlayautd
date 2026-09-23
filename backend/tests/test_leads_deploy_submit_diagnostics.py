"""Mantiene el rechazo visual y la evidencia HTTP sin exponer credenciales."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.app.config.settings import Settings
from backend.app.modules.bot_leads_deploy.runner import (
    RejectedSubmission, UnconfirmedSubmission, UtelInconcertRunner,
)


def test_visible_rejection_preserves_http_status_and_excludes_personal_data():
    runner = UtelInconcertRunner(Settings())
    response = SimpleNamespace(status=500, text=AsyncMock(return_value='Internal server error'), request=SimpleNamespace(post_data_json={
        'formId': '151', 'integration': 'balanceador', 'token': 'SECRET_TOKEN',
        'inputs': {'first_name': 'PRIVATE_NAME', 'email': 'PRIVATE_EMAIL', 'phone': {'number': 'PRIVATE_PHONE'}, 'area': 'Diplomados', 'program': 'Programa', 'siuKey': None},
    }))
    with pytest.raises(RejectedSubmission) as error:
        asyncio.run(runner._classify_utel_api_response(response, 'Error al enviar\nContacta a soporte'))
    message = str(error.value)
    assert 'HTTP 500' in message and 'Internal server error' in message
    assert '151' in message and 'balanceador' in message
    assert 'SECRET_TOKEN' not in message and 'PRIVATE_' not in message


def test_http_500_without_visible_rejection_remains_unconfirmed():
    runner = UtelInconcertRunner(Settings())
    response = SimpleNamespace(status=500, text=AsyncMock(return_value='Internal server error'), request=SimpleNamespace(post_data_json={}))
    with pytest.raises(UnconfirmedSubmission):
        asyncio.run(runner._classify_utel_api_response(response))
