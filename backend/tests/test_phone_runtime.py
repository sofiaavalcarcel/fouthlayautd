import httpx
import pytest
from backend.app.services.test_lead_service import TestLeadService
from backend.app.services.ai_service import AIService


@pytest.mark.parametrize('country', TestLeadService.COUNTRY_REGIONS)
def test_generated_phone_is_valid_and_unique(country, tmp_path):
    service = TestLeadService(tmp_path / 'qa.db', allow_synthetic_real_phones=True)
    leads = service.reserve_many([country] * 3)
    assert len({lead['phone'] for lead in leads}) == 3
    assert all(service._is_valid_generated_phone(lead['phone'], country) for lead in leads)


@pytest.mark.parametrize('payload', [
    {'error': 'model unavailable'}, {'error': {'message': 'model unavailable'}},
    'model unavailable',
])
def test_ollama_error_formats(payload):
    response = httpx.Response(404, json=payload)
    assert 'model unavailable' in AIService._provider_error_message(response)
