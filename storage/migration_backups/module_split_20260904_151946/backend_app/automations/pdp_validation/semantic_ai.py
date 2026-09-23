"""Capa opcional de interpretación semántica con respaldo automático."""

from __future__ import annotations

import json
from typing import Any

from ...services.ai_service import AIProviderError, AIService
from .models import SemanticDocument


SYSTEM_PROMPT = """Eres un auditor de QA de contenido. No inventes datos. Solo puedes proponer equivalencias usando los candidatos de la página recibidos. Devuelve únicamente JSON válido con esta forma: {\"matches\":[{\"expected_id\":\"\",\"actual_id\":\"\",\"status\":\"POSIBLE_COINCIDENCIA\" o \"REVISION_MANUAL\",\"confidence\":0.0,\"reason\":\"\",\"actual\":\"\"}]}. Si no hay evidencia, usa REVISION_MANUAL. Nunca marques un caso como coincidencia exacta."""


class SemanticAIOrchestrator:
    """Usa Gemini, luego Groq y finalmente Ollama local como respaldo."""

    PROVIDER_ORDER = (("gemini", False), ("groq", False), ("ollama", True))

    def __init__(self, ai_service: AIService):
        self.ai_service = ai_service

    async def resolve(self, expected: SemanticDocument, actual: SemanticDocument, unresolved: list[dict[str, Any]]) -> dict[str, Any]:
        if not unresolved:
            return {"findings": [], "providers": [], "ai_used": False, "fallback_mode": "not_needed"}

        expected_payload = [item["document_node"] for item in unresolved[:30]]
        candidates = [
            {
                "expected_id": item["expected_id"],
                "expected": item["expected"],
                "section": item["section"],
                "candidates": item["candidates"],
            }
            for item in unresolved[:30]
        ]
        prompt = json.dumps({"expected": expected_payload, "page_candidates": candidates}, ensure_ascii=False)
        configured = {item["provider"]: item["configured"] for item in self.ai_service.provider_statuses()}
        providers: list[dict[str, Any]] = []

        parsed, successful_provider = await self._ask_with_fallback(
            prompt,
            configured,
            providers,
            stage="semantic_review",
        )
        if not parsed:
            return {
                "findings": [],
                "providers": providers,
                "ai_used": False,
                "fallback_mode": "deterministic",
                "manual_review_required": len(unresolved),
                "message": "Las IAs no estuvieron disponibles; se conserva el resultado del comparador determinístico.",
            }

        final_matches = parsed.get("matches", [])
        return {
            "findings": self._sanitize_matches(final_matches, unresolved),
            "providers": providers,
            "ai_used": True,
            "fallback_mode": "none" if successful_provider == "gemini" else f"used_{successful_provider}",
            "successful_provider": successful_provider,
        }

    async def _ask_with_fallback(
        self,
        prompt: str,
        configured: dict[str, bool],
        providers: list[dict[str, Any]],
        *,
        stage: str,
    ) -> tuple[dict[str, Any] | None, str | None]:
        """Prueba proveedores en orden y continúa ante cuota, red o error de formato."""

        for position, (provider, local) in enumerate(self.PROVIDER_ORDER, start=1):
            if not configured.get(provider):
                providers.append({"provider": provider, "stage": stage, "status": "not_configured", "attempt": position})
                continue
            try:
                result = await self.ai_service.generate(provider, prompt, system_instruction=SYSTEM_PROMPT, local=local)
                parsed = self._parse_json(result.text)
                if not parsed.get("matches"):
                    raise ValueError("La IA no devolvió candidatos semánticos.")
                providers.append({
                    "provider": provider,
                    "stage": stage,
                    "status": "ok",
                    "attempt": position,
                    "model": result.model,
                    "usage": result.usage,
                    "rate_limits": result.rate_limits,
                })
                return parsed, provider
            except Exception as error:  # noqa: BLE001 - un proveedor no debe bloquear el comparador
                details: dict[str, Any] = {
                    "provider": provider,
                    "stage": stage,
                    "status": "quota_exhausted" if isinstance(error, AIProviderError) and error.kind == "quota" else "error",
                    "attempt": position,
                    "message": str(error)[:200],
                }
                if isinstance(error, AIProviderError):
                    details["error_kind"] = error.kind
                    details["status_code"] = error.status_code
                providers.append(details)

        return None, None

    @staticmethod
    def _parse_json(text: str) -> dict[str, Any]:
        cleaned = text.strip().replace("```json", "").replace("```", "").strip()
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("La IA no devolvió JSON válido.")
        value = json.loads(cleaned[start : end + 1])
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _sanitize_matches(matches: list[dict[str, Any]], unresolved: list[dict[str, Any]]) -> list[dict[str, Any]]:
        allowed = {item["expected_id"]: {candidate["actual_id"]: candidate["actual"] for candidate in item["candidates"]} for item in unresolved}
        safe = []
        for item in matches:
            expected_id, actual_id = item.get("expected_id"), item.get("actual_id")
            if expected_id not in allowed or actual_id not in allowed[expected_id]:
                continue
            safe.append({
                "expected_id": expected_id,
                "actual": allowed[expected_id][actual_id],
                "confidence": max(0.0, min(1.0, float(item.get("confidence", 0)))),
                "reason": str(item.get("reason") or "Equivalencia propuesta por la capa semántica."),
                "candidates": [{"actual_id": actual_id, "actual": allowed[expected_id][actual_id]}],
            })
        return safe
