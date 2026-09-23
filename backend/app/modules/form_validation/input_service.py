"""Construcción de una matriz temporal para URLs pegadas manualmente."""

from __future__ import annotations

import io
from typing import Iterable

from openpyxl import Workbook


class FormValidationInputService:
    """Convierte URLs de la interfaz en el mismo contrato Excel del lote actual."""

    HEADERS = ("Country", "URL", "Formulario", "Lead")

    @classmethod
    def workbook_bytes(cls, urls: Iterable[str], country: str = "") -> bytes:
        """Crea un XLSX temporal; los datos reales siguen siendo procesados por el runner existente."""

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Form Validation"
        sheet.append(list(cls.HEADERS))
        for url in urls:
            sheet.append([country, str(url).strip(), "", ""])
        output = io.BytesIO()
        workbook.save(output)
        return output.getvalue()

    @classmethod
    def mapping(cls) -> dict[str, str]:
        """Devuelve el mapeo estable usado por el endpoint interno del lote."""

        return {
            "country": "Country",
            "utel_url": "URL",
            "form_type": "Formulario",
            "lead_url": "Lead",
        }
