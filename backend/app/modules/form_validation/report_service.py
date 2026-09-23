"""Reporte ordenado específico para URLs de Form Validation."""

from __future__ import annotations

from typing import Any

from ...services.bot_report_service import BotReportService
from ...services.bot_spreadsheet_service import BotSpreadsheetService


class FormValidationReportService(BotReportService):
    """Añade columnas de conciliación sin alterar las columnas de entrada."""

    COLUMNS = (
        "URL",
        "País",
        "Nombre",
        "Correo",
        "Teléfono",
        "Nivel seleccionado",
        "Programa seleccionado",
        "Estado formulario",
        "Encontrado en inConcert",
        "Link inConcert",
        "Encontrado en Balancer",
        "Link Balancer",
        "Fuente final",
        "Tiempo de búsqueda",
        "Error",
    )

    def build(self, content: bytes, mapping: dict[str, Any], results: list[dict[str, Any]]):
        """Construye el reporte histórico y completa la vista tabular estándar."""

        workbook = super().build(content, mapping, results)
        service = BotSpreadsheetService()
        for sheet in workbook.worksheets:
            items = [item for item in results if item.get("row", {}).get("sheet") == sheet.title]
            if not items:
                continue
            header_index = service._header_index(list(sheet.iter_rows(values_only=True)))
            if header_index is None:
                continue
            header_row = header_index + 1
            positions = {}
            for label in self.COLUMNS:
                normalized = service._normalize(label)
                positions[label] = next(
                    (cell.column for cell in sheet[header_row] if service._normalize(service._text(cell.value)) == normalized),
                    None,
                )
                if positions[label] is None:
                    positions[label] = sheet.max_column + 1
                    sheet.cell(header_row, positions[label], label)
            for item in items:
                row_number = item["row"]["row_number"]
                result = item.get("result", {})
                failure = next(
                    (stage.get("message", "") for stage in result.get("stages", []) if stage.get("status") == "FAIL"),
                    "",
                )
                values = {
                    "URL": item["row"].get("utel_url", ""),
                    "País": result.get("country") or item["row"].get("country", ""),
                    "Nombre": result.get("lead_name", ""),
                    "Correo": result.get("lead_email", ""),
                    "Teléfono": result.get("lead_phone", ""),
                    "Nivel seleccionado": result.get("level", ""),
                    "Programa seleccionado": result.get("selected_program_name", ""),
                    "Estado formulario": (
                        "Rellenado sin envío"
                        if result.get("fill_only")
                        else result.get("utel_submission", "")
                    ),
                    "Encontrado en inConcert": "Sí" if result.get("found_inconcert") else "No",
                    "Link inConcert": result.get("inconcert_lead_url", ""),
                    "Encontrado en Balancer": "Sí" if result.get("found_balancer") else "No",
                    "Link Balancer": result.get("balancer_lead_url", ""),
                    "Fuente final": result.get("source_final") or result.get("lead_source", ""),
                    "Tiempo de búsqueda": result.get("search_duration_seconds", 0),
                    "Error": failure or result.get("error", "") or ("" if result.get("status") == "PASS" else result.get("summary", "")),
                }
                for label, value in values.items():
                    sheet.cell(row_number, positions[label], value)
        # Hoja plana con el orden contractual solicitado, sin reordenar ni
        # perder las columnas originales que el usuario cargó.
        summary_sheet = workbook.create_sheet("Form Validation resultados")
        summary_sheet.append(list(self.COLUMNS))
        for item in results:
            result = item.get("result", {})
            failure = next(
                (stage.get("message", "") for stage in result.get("stages", []) if stage.get("status") == "FAIL"),
                "",
            )
            summary_sheet.append([
                item.get("row", {}).get("utel_url", ""),
                result.get("country") or item.get("row", {}).get("country", ""),
                result.get("lead_name", ""),
                result.get("lead_email", ""),
                result.get("lead_phone", ""),
                result.get("level", ""),
                result.get("selected_program_name", ""),
                "Rellenado sin envío" if result.get("fill_only") else result.get("utel_submission", ""),
                "Sí" if result.get("found_inconcert") else "No",
                result.get("inconcert_lead_url", ""),
                "Sí" if result.get("found_balancer") else "No",
                result.get("balancer_lead_url", ""),
                result.get("source_final") or result.get("lead_source", ""),
                result.get("search_duration_seconds", 0),
                failure or result.get("error", "") or ("" if result.get("status") == "PASS" else result.get("summary", "")),
            ])
            current_row = summary_sheet.max_row
            for label in ("Link inConcert", "Link Balancer"):
                column = self.COLUMNS.index(label) + 1
                link = summary_sheet.cell(current_row, column).value
                if link:
                    summary_sheet.cell(current_row, column).hyperlink = str(link)
                    summary_sheet.cell(current_row, column).style = "Hyperlink"
        return workbook
