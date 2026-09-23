"""Orquestador genérico Documento vs Página para el módulo PDP."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from playwright.async_api import async_playwright

from ..automations.pdp_validation.comparison_engine import ComparisonEngine
from ..automations.pdp_validation.document_parser import DocumentParser
from ..automations.pdp_validation.semantic_ai import SemanticAIOrchestrator
from ..automations.pdp_validation.web_parser import WebPageParser
from ..config.settings import Settings
from .ai_service import AIService


MAX_FILE_SIZE = 25 * 1024 * 1024
SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".txt", ".md", ".csv"}


class GenericPdpValidationService:
    """Ejecuta extracción, comparación, revisión semántica y persistencia del reporte."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.document_parser = DocumentParser()
        self.web_parser = WebPageParser()
        self.comparison_engine = ComparisonEngine()

    async def validate(self, filename: str, source_bytes: bytes, url: str, use_ai: bool = True) -> dict[str, Any]:
        started_at = datetime.now().isoformat(timespec="seconds")
        timer = perf_counter()
        self._validate_input(filename, source_bytes, url)
        expected = self.document_parser.parse(filename, source_bytes)
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                actual = await self.web_parser.parse(page, url)
            finally:
                await browser.close()

        comparison = self.comparison_engine.compare(expected, actual)
        ai_report: dict[str, Any] = {"enabled": use_ai, "used": False, "providers": []}
        if use_ai and comparison["unresolved"]:
            ai_report = await SemanticAIOrchestrator(AIService(self.settings)).resolve(expected, actual, comparison["unresolved"])
            self.comparison_engine.apply_ai_findings(comparison, ai_report.get("findings", []))
            ai_report = {"enabled": True, **ai_report}
        summary = self.comparison_engine.summarize(comparison)
        blocking = summary["different"] + summary["missing"] + summary["extra"] + summary["duplicates"] + summary["manual_review"] + summary["possible_matches"]
        report = {
            "status": "PASS" if blocking == 0 else "WARNING",
            "started_at": started_at,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "duration_seconds": round(perf_counter() - timer, 2),
            "source_filename": filename,
            "url": url,
            "source": expected.to_dict(),
            "page": actual.to_dict(),
            "summary": summary,
            "findings": comparison["findings"],
            "ai": ai_report,
        }
        report_path = self.settings.storage_dir / "reports" / "pdp" / f"semantic-{uuid4().hex}.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report["report_file"] = str(report_path)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report

    @staticmethod
    def _validate_input(filename: str, source_bytes: bytes, url: str) -> None:
        extension = Path(filename or "").suffix.lower()
        parsed = urlparse(url or "")
        if extension not in SUPPORTED_EXTENSIONS:
            raise ValueError("Formato no soportado. Usa PDF, DOCX, XLSX, TXT, MD o CSV.")
        if not source_bytes or len(source_bytes) > MAX_FILE_SIZE:
            raise ValueError("El documento está vacío o supera el límite de 25 MB.")
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("La URL debe comenzar con http:// o https://.")
