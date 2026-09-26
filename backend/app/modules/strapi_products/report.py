from __future__ import annotations

import io
import json
from datetime import datetime, timezone

from openpyxl import Workbook

from .models import ProductResult, ProductSummary


def _json(value):
    return json.dumps(value, ensure_ascii=False, default=str) if not isinstance(value, str) else value


def _append_diagnostics_sheet(workbook, results):
    diagnostics = workbook.create_sheet("Diagnóstico")
    generated_at = datetime.now(timezone.utc).isoformat()
    diagnostics.append([
        "Producto", "Estado", "Sección", "Campo", "Resultado", "Código", "Severidad",
        "Mensaje", "Explicación", "Acción recomendada", "Fuente utilizada", "Fecha",
    ])
    for result in results:
        values = result if isinstance(result, dict) else result.as_dict()
        for item in values.get("diagnostics", []):
            diagnostics.append([
                values.get("program"), values.get("status"), item.get("section"), item.get("field"),
                "Advertencia" if item.get("severity") == "warning" else "Información" if item.get("severity") == "info" else "Error",
                item.get("code"), item.get("severity"), item.get("message"),
                item.get("explanation"), item.get("action"), item.get("source"), generated_at,
            ])


def build_report(results: list[ProductResult], summary: ProductSummary) -> bytes:
    workbook = Workbook()
    detail = workbook.active
    detail.title = "Resultados"
    detail.append(["Hoja", "Fila", "Programa", "Pais", "Estado", "Canonical anterior", "Canonical nuevo", "Mensaje", "Diagnósticos"])
    for result in results:
        detail.append([result.sheet, result.row_number, result.program, result.country, result.status, result.old_canonical, result.new_canonical, result.message, len(result.diagnostics)])

    overview = workbook.create_sheet("Resumen")
    overview.append(["Metrica", "Valor"])
    for key, value in summary.as_dict().items():
        overview.append([key, value])

    _append_diagnostics_sheet(workbook, [result.as_dict() for result in results])
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def build_description_report(results: list[ProductResult], summary: ProductSummary) -> bytes:
    workbook = Workbook()
    detail = workbook.active
    detail.title = "Resultados"
    detail.append(["Hoja", "Fila", "Programa", "Pais", "Estado", "siuKey", "bannerKey", "Descripcion extraida", "Cambios", "Campos conservados", "Verificacion", "Mensaje", "Fuentes"])
    for result in results:
        detail.append([
            result.sheet, result.row_number, result.program, result.country, result.status,
            result.siu_key, result.banner_key, result.description, len(result.changes),
            len(result.preserved_fields), result.verification.get("ok"), result.message,
            _json(result.sources),
        ])
    overview = workbook.create_sheet("Resumen")
    overview.append(["Metrica", "Valor"])
    for key, value in summary.as_dict().items():
        overview.append([key, value])
    overview.append(["cambios_propuestos_o_aplicados", sum(len(result.changes) for result in results)])
    overview.append(["productos_verificados", sum(result.verification.get("ok") is True for result in results)])
    overview.append(["diagnosticos", sum(len(result.diagnostics) for result in results)])
    overview.append(["campos_conservados", sum(len(result.preserved_fields) for result in results)])

    plan = workbook.create_sheet("Plan por producto")
    plan.append(["Hoja", "Fila", "Programa", "Estado", "Campo", "Accion", "Antes", "Despues", "Verificado", "ID creado"])
    for result in results:
        for change in result.changes:
            before = _json(change.get("before"))
            after = _json(change.get("after"))
            plan.append([
                result.sheet, result.row_number, result.program, result.status,
                change.get("field"), change.get("action"), before, after,
                change.get("verified"), change.get("created_id"),
            ])
    _append_diagnostics_sheet(workbook, [result.as_dict() for result in results])
    preserved = workbook.create_sheet("Campos conservados")
    preserved.append(["Hoja", "Fila", "Programa", "Campo", "Motivo"])
    for result in results:
        for field in result.preserved_fields:
            preserved.append([result.sheet, result.row_number, result.program, field, "Ya coincidía con el documento o no fue gestionado por esta fuente."])
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def build_combined_report(canonical_job: dict, pdp_job: dict) -> bytes:
    """Build one workbook with both stages of a PDP product synchronization."""
    workbook = Workbook()
    detail = workbook.active
    detail.title = "Resultados"
    detail.append([
        "Proceso", "Hoja", "Fila", "Programa", "Pais", "Estado", "Canonical anterior",
        "Canonical nuevo", "siuKey", "bannerKey", "Descripcion extraida", "Verificacion", "Mensaje", "Diagnósticos",
    ])
    all_results = [("Canonical", item) for item in canonical_job.get("results", [])]
    all_results += [("PDP", item) for item in pdp_job.get("results", [])]
    for process, result in all_results:
        detail.append([
            process, result.get("sheet"), result.get("row_number"), result.get("program"),
            result.get("country"), result.get("status"), result.get("old_canonical"),
            result.get("new_canonical"), result.get("siu_key"), result.get("banner_key"),
            result.get("description"), result.get("verification", {}).get("ok"), result.get("message"),
            len(result.get("diagnostics", [])),
        ])

    overview = workbook.create_sheet("Resumen")
    overview.append(["Proceso", "Estado", "Metrica", "Valor"])
    for process, job in (("Canonical", canonical_job), ("PDP", pdp_job)):
        summary = job.get("summary", {})
        overview.append([process, job.get("status"), "total", summary.get("total", 0)])
        for key, value in summary.items():
            if key != "total":
                overview.append([process, job.get("status"), key, value])

    plan = workbook.create_sheet("Plan por producto")
    plan.append(["Proceso", "Hoja", "Fila", "Programa", "Estado", "Campo", "Accion", "Antes", "Despues", "Verificado", "ID creado"])
    for process, result in all_results:
        for change in result.get("changes", []):
            before = _json(change.get("before"))
            after = _json(change.get("after"))
            plan.append([
                process, result.get("sheet"), result.get("row_number"), result.get("program"),
                result.get("status"), change.get("field"), change.get("action"), before, after,
                change.get("verified"), change.get("created_id"),
            ])

    _append_diagnostics_sheet(workbook, [result for _, result in all_results])
    preserved = workbook.create_sheet("Campos conservados")
    preserved.append(["Proceso", "Hoja", "Fila", "Programa", "Campo", "Motivo"])
    for process, result in all_results:
        for field in result.get("preserved_fields", []):
            preserved.append([process, result.get("sheet"), result.get("row_number"), result.get("program"), field, "Ya coincidía con el documento o no fue gestionado por esta fuente."])

    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()
