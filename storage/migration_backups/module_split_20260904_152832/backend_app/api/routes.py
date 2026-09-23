"""Endpoints REST de la Fase 1."""

import json
import asyncio
import os
import re
from datetime import date, datetime
from uuid import uuid4
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse

from ..automations.generic_bot.runner import BotRunner
from ..automations.utel_inconcert.runner import UtelInconcertRunner, UtelRunCancelled
from ..automations.leads_deploy.runner import LeadsDeployRunner
from ..automations.weekly_auto.runner import WeeklyAutoRunner
from ..database.repository import ExecutionRepository
from ..database.connection import get_connection
from ..schemas.bot import (
    BotConfig,
    BotJobResponse,
    BotRunResponse,
    BotStartResponse,
    UtelQaConfig,
    UtelQaJobResponse,
)
from ..schemas.weekly_auto import (
    WeeklyAutoConfig,
    WeeklyAutoJobResponse,
)
from ..schemas.ai import AICompletionRequest, AICompletionResponse, AIProvidersResponse
from ..schemas.recorder import (
    RecorderEventsResponse,
    RecorderStartRequest,
    RecorderStartResponse,
    RecorderStopResponse,
)
from ..schemas.execution import (
    DashboardSummary,
    ExecutionListResponse,
    HealthResponse,
)
from ..services.dashboard_service import DashboardService
from ..services.ai_service import AIService
from ..services.logging_service import get_logger
from ..services.pdp_validation_service import PdpValidationService
from ..services.generic_pdp_validation_service import GenericPdpValidationService
from ..services.bot_spreadsheet_service import BotSpreadsheetService
from ..services.leads_deploy_spreadsheet_service import LeadsDeploySpreadsheetService
from ..services.bot_report_service import BotReportService
from ..services.test_lead_service import TestLeadService


router = APIRouter(prefix="/api")


def _batch_dry_run(raw_config: dict[str, Any]) -> bool:
    """Obtiene el modo seguro sin aceptar cadenas ambiguas como ``"false"``."""

    value = raw_config.get("dry_run", True)
    if not isinstance(value, bool):
        raise ValueError("El campo dry_run debe ser booleano (true o false).")
    return value


def _is_new_products_scope(sheet_name: str, filename: str) -> bool:
    """Detecta documentos orientados a links directos de nuevos productos."""

    source = f"{sheet_name} {filename}".casefold()
    return "nuevos productos" in source


def _save_utel_batch_report(
    settings: Any,
    job_id: str,
    filename: str,
    content: bytes,
    mapping: dict[str, Any],
    results: list[dict[str, Any]],
) -> None:
    """Guarda un checkpoint descargable, incluso mientras el lote sigue activo."""

    if not results:
        return
    output_dir = settings.storage_dir / "reports" / "bot"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{job_id}_{filename.rsplit('.', 1)[0]}.xlsx"
    temporary_path = output_path.with_name(
        f".{output_path.name}.{uuid4().hex}.tmp"
    )
    try:
        # El ZIP de Excel se escribe completo en el mismo volumen y solo luego
        # reemplaza el checkpoint anterior. Un cierre forzado nunca trunca el
        # último reporte válido.
        BotReportService().build(content, mapping, results).save(temporary_path)
        os.replace(temporary_path, output_path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _merge_utel_and_crm_results(
    submission: dict[str, Any],
    verification: dict[str, Any],
) -> dict[str, Any]:
    """Fusiona ambas fases sin perder la evidencia obtenida antes de consultar CRM.

    El mensaje visual de UTEL es solo una señal de diagnóstico. Después de haber
    hecho clic, la existencia del lead en CRM es la fuente de verdad y nunca se
    vuelve a enviar el formulario para intentar cambiar ese resultado.
    """

    original_notice = str(submission.get("utel_submission_message") or "").strip()
    crm_confirmed = bool(verification.get("lead_url")) and (
        verification.get("lead_found") == "success"
        # Compatibilidad con resultados antiguos: antes de exponer lead_found,
        # un PASS con URL de detalle ya demostraba que CRM encontró el contacto.
        or (
            verification.get("lead_found") is None
            and verification.get("status") == "PASS"
        )
    )

    # La verificación contiene el estado final del flujo; estos campos pertenecen
    # a la fase UTEL y deben sobrevivir aunque verification_only los marque skipped.
    merged = {
        **verification,
        "selected_program_name": (
            submission.get("selected_program_name")
            or verification.get("selected_program_name")
            or ""
        ),
        "program_selection_notice": (
            submission.get("program_selection_notice")
            or verification.get("program_selection_notice")
            or ""
        ),
        "utel_submission_attempted": bool(
            submission.get("utel_submission_attempted", True)
        ),
        "stages": [
            *submission.get("stages", []),
            *verification.get("stages", []),
        ],
        "screenshots": list(
            dict.fromkeys(
                [
                    *submission.get("screenshots", []),
                    *verification.get("screenshots", []),
                ]
            )
        ),
    }

    notice_suffix = f" Aviso original de UTEL: {original_notice}" if original_notice else ""
    if crm_confirmed:
        merged["utel_submission"] = "success"
        merged["lead_found"] = "success"
        merged["utel_submission_message"] = (
            "Lead confirmado en CRM sin reenviar el formulario."
            f"{notice_suffix}"
        )
    elif verification.get("lead_found") == "failed":
        # Un toast rojo o la falta de confirmación visual no autorizan otro clic.
        # Si ambos buscadores agotaron su ventana, la fila termina como fallo.
        merged["status"] = "FAIL"
        merged["utel_submission"] = "failed"
        merged["lead_found"] = "failed"
        merged["summary"] = (
            "CRM no confirmó el lead y el formulario no se reenvió para evitar duplicados."
        )
        merged["utel_submission_message"] = (
            "CRM no confirmó el lead; no se reenvió el formulario para evitar duplicados."
            f"{notice_suffix}"
        )
    else:
        # Una caída de login/red no demuestra que UTEL haya rechazado el lead.
        # Conservamos el intento como pendiente para que nadie lo reenvíe por error.
        merged["status"] = "FAIL"
        merged["utel_submission"] = "pending"
        merged["lead_found"] = "pending"
        merged["summary"] = (
            "No se pudo completar la verificación CRM; el formulario no se reenvió."
        )
        merged["utel_submission_message"] = (
            "Verificación CRM pendiente; no se reenvió el formulario para evitar duplicados."
            f"{notice_suffix}"
        )
    # Conserva en el Excel el historial de teléfonos usados durante los
    # reintentos, incluso cuando la verificación CRM reconstruye el resultado.
    if submission.get("retry_history"):
        merged["retry_attempts"] = submission.get("retry_attempts", 0)
        merged["retry_history"] = list(submission["retry_history"])
        if not crm_confirmed:
            merged["summary"] = (
                f"{merged.get('summary', '')} Se agotaron los reintentos automáticos; "
                "realiza este caso manualmente."
            ).strip()
            merged["utel_submission_message"] = (
                f"{merged.get('utel_submission_message', '')} "
                "Se agotaron los reintentos automáticos; realiza este caso manualmente."
            ).strip()
    return merged


def _utel_batch_counts(results: list[dict[str, Any]]) -> dict[str, int]:
    """Cuenta únicamente resultados definitivos; un envío pendiente no es éxito."""

    success = 0
    failed = 0
    pending = 0
    for item in results:
        result = item.get("result", {})
        if (
            result.get("utel_submission") == "pending"
            and result.get("utel_submission_attempted") is not False
        ):
            pending += 1
        elif result.get("status") == "FAIL":
            failed += 1
        elif result.get("dry_run") and result.get("status") == "PASS":
            # El dry run termina en UTEL y no necesita una conciliación posterior.
            success += 1
        elif (
            result.get("status") == "PASS"
            and result.get("lead_found") == "success"
            and bool(result.get("lead_url"))
        ):
            success += 1
        else:
            pending += 1
    return {"success": success, "failed": failed, "pending": pending}


def _is_support_rejection(result: dict[str, Any]) -> bool:
    """Identifica solo el rechazo explícito de UTEL que admite reintento."""

    # Si CRM ya entregó un enlace, no se debe volver a enviar aunque UTEL haya
    # mostrado un aviso ambiguo después del clic.
    if result.get("lead_url"):
        return False
    texts = [
        str(result.get("utel_submission_message") or ""),
        str(result.get("summary") or ""),
        *[
            str(stage.get("message") or "")
            for stage in result.get("stages", [])
            if isinstance(stage, dict)
        ],
    ]
    combined = " ".join(texts)
    return bool(
        re.search(
            r"error\s+al\s+enviar|contacta\s+a\s+soporte|rejected\s+post",
            combined,
            re.IGNORECASE,
        )
    )


def _is_post_submit_crm_retry_candidate(result: dict[str, Any]) -> bool:
    """Permite una segunda consulta CRM cuando UTEL ya fue enviado."""

    if result.get("utel_submission_attempted") is not True:
        return False

    failed_stage = next(
        (
            stage
            for stage in result.get("stages", [])
            if isinstance(stage, dict) and stage.get("status") == "FAIL"
        ),
        None,
    )
    if not failed_stage:
        return False

    stage_name = str(failed_stage.get("stage") or "")
    return (
        stage_name.startswith("inconcert_")
        or stage_name.startswith("lead_balancer_")
    )


def _is_safe_visible_retry_candidate(result: dict[str, Any]) -> bool:
    """Reintenta una vez en navegador visible solo cuando todavía no hubo envío."""

    if result.get("utel_submission_attempted") is not False:
        return False

    failed_stage = next(
        (
            stage
            for stage in result.get("stages", [])
            if isinstance(stage, dict) and stage.get("status") == "FAIL"
        ),
        None,
    )
    if not failed_stage:
        return False

    stage_name = str(failed_stage.get("stage") or "")
    return stage_name in {
        "utel_access",
        "utel_open",
        "utel_navigation",
        "utel_form",
        "utel_fill",
        "utel_submit",
    }


def _is_temporary_access_block(result: dict[str, Any]) -> bool:
    """Reconoce bloqueos temporales que admiten un solo reintento al final."""

    texts = [
        str(result.get("summary") or ""),
        str(result.get("utel_submission_message") or ""),
        *[
            str(stage.get("message") or "")
            for stage in result.get("stages", [])
            if isinstance(stage, dict)
        ],
    ]
    return bool(
        re.search(
            r"cloudflare|sorry,?\s+you\s+have\s+been\s+blocked|"
            r"you\s+are\s+unable\s+to\s+access|bloqueo\s+esta\s+sesion|"
            r"bloque[oó]\s+el\s+acceso\s+de\s+esta\s+sesion|"
            r"no\s+se\s+encontr[oó]\s+el\s+campo\s+usuario\s+en\s+el\s+balanceador|"
            r"pantalla\s+de\s+login.*campos.*no.*cargar",
            " ".join(texts),
            re.IGNORECASE,
        )
    )


def _is_balanceador_url(url: str) -> bool:
    """Clasifica una URL de origen lead sin depender del nombre de la columna."""

    value = str(url or "").casefold()
    return "balance" in value or "lead-balancer" in value


US_QA_AREA_CODES = (
    "202", "212", "213", "305", "312", "347", "415", "424", "469", "512",
    "617", "646", "702", "703", "713", "718", "786", "917", "929", "954",
    "972",
)


def _extract_ai_phone_candidate(value: str) -> str:
    """Extrae un único teléfono nacional de una respuesta de Ollama."""

    matches = re.findall(r"(?<!\d)(\d{7,15})(?!\d)", str(value or ""))
    if len(matches) != 1:
        raise ValueError("Ollama no devolvió un único teléfono nacional.")
    return matches[0]


def _country_phone_rule(
    lead_service: TestLeadService,
    country: str,
) -> tuple[str, int] | None:
    """Devuelve prefijo nacional esperado y cantidad de dígitos del país."""

    normalized = lead_service._normalize(country)
    return lead_service.PHONE_FORMATS.get(normalized)


def _phone_matches_country_rule(
    lead_service: TestLeadService,
    country: str,
    phone: str,
) -> bool:
    """Comprueba estructura local antes de permitir que el número llegue a UTEL."""

    rule = _country_phone_rule(lead_service, country)
    if rule is None:
        return False

    prefix, total_digits = rule
    return (
        phone.isdigit()
        and len(phone) == total_digits
        and phone.startswith(prefix)
    )


def _is_safe_us_synthetic_phone(phone: str) -> bool:
    """Acepta solo números QA NPA-555-0100..0199 de códigos permitidos."""

    if not re.fullmatch(r"\d{10}", phone):
        return False
    if phone[:3] not in US_QA_AREA_CODES:
        return False
    if phone[3:6] != "555":
        return False
    return 100 <= int(phone[-4:]) <= 199


def _reserve_specific_test_phone(
    settings: Any,
    lead_service: TestLeadService,
    country_label: str,
    phone: str,
) -> dict[str, Any] | None:
    """Reserva un número concreto si sigue libre al abrir la transacción."""

    today = date.today().isoformat()

    with get_connection(settings.database_path) as connection:
        connection.execute("BEGIN IMMEDIATE")

        exists = connection.execute(
            "SELECT 1 FROM test_leads WHERE phone = ? LIMIT 1",
            (phone,),
        ).fetchone()
        if exists:
            connection.rollback()
            return None

        next_sequence = connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 "
            "FROM test_leads WHERE test_date = ?",
            (today,),
        ).fetchone()[0]
        phone_sequence = connection.execute(
            "SELECT COALESCE(MAX(id), 0) + 1 FROM test_leads"
        ).fetchone()[0]

        email = f"Testing{today}N{next_sequence}@testingUtel.com"
        name = f"Danilo Prueba {lead_service._alphabetic_sequence(phone_sequence)}"

        connection.execute(
            "INSERT INTO test_leads "
            "(test_date, sequence, country, email, phone, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                today,
                next_sequence,
                country_label,
                email,
                phone,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )

    return {
        "name": name,
        "email": email,
        "phone": phone,
        "country": country_label,
        "sequence": next_sequence,
    }


def _fallback_us_test_lead(
    settings: Any,
    lead_service: TestLeadService,
    country_label: str,
    normalized_country: str,
) -> dict[str, Any]:
    """Pool local amplio de respaldo para Estados Unidos."""

    with get_connection(settings.database_path) as connection:
        used = {
            str(row[0])
            for row in connection.execute("SELECT phone FROM test_leads")
        }
        seed = int(
            connection.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM test_leads")
            .fetchone()[0]
        )

    capacity = len(US_QA_AREA_CODES) * 100
    start = (seed * 7919) % capacity

    for offset in range(capacity):
        position = (start + offset) % capacity
        area_code = US_QA_AREA_CODES[position // 100]
        line_number = 100 + (position % 100)
        phone = f"{area_code}555{line_number:04d}"

        if phone in used:
            continue

        if (
            lead_service.allow_synthetic_real_phones
            and not lead_service._is_valid_generated_phone(phone, normalized_country)
        ):
            continue

        reserved = _reserve_specific_test_phone(
            settings,
            lead_service,
            country_label,
            phone,
        )
        if reserved is not None:
            logger.info(
                "Se usó fallback local QA para %s después de no obtener un número nuevo de Ollama.",
                country_label,
            )
            return reserved

    raise ValueError(
        f"No quedan teléfonos sintéticos QA disponibles para {country_label}."
    )


def _ollama_phone_prompt(
    lead_service: TestLeadService,
    country_label: str,
    used: set[str],
    attempt: int,
) -> str:
    """Construye una instrucción específica para el país de la fila."""

    normalized_country = lead_service._normalize(country_label)
    prefix, total_digits = lead_service.PHONE_FORMATS[normalized_country]
    us_aliases = {"usa", "united states", "estados unidos", "global"}

    recent_used = [
        phone
        for phone in sorted(used)
        if phone.isdigit() and len(phone) == total_digits
    ][-60:]
    forbidden = ", ".join(recent_used) if recent_used else "ninguno"
    nonce = uuid4().hex[:12]

    if normalized_country in us_aliases:
        area_codes = ", ".join(US_QA_AREA_CODES)
        return (
            "Genera exactamente UN teléfono sintético de Estados Unidos para QA. "
            "Responde únicamente con 10 dígitos, sin espacios, texto ni JSON. "
            "Formato obligatorio: NPA55501XX. "
            f"NPA debe ser uno de estos códigos: {area_codes}. "
            "XX debe estar entre 00 y 99. "
            f"No uses ninguno de estos números ya reservados: {forbidden}. "
            f"Identificador único de solicitud: {nonce}. "
            f"Intento {attempt}. Devuelve un número diferente."
        )

    return (
        f"Genera exactamente UN teléfono nacional sintético para pruebas QA de {country_label}. "
        "Responde únicamente con los dígitos nacionales, sin código internacional, "
        "sin signo +, espacios, texto ni JSON. "
        f"Debe tener exactamente {total_digits} dígitos y comenzar con {prefix}. "
        f"No uses ninguno de estos números ya reservados: {forbidden}. "
        f"Identificador único de solicitud: {nonce}. "
        f"Intento {attempt}. Devuelve un número diferente."
    )


async def _reserve_lead_for_case(
    settings: Any,
    lead_service: TestLeadService,
    country: str,
    *,
    require_authorized_phone: bool,
) -> dict[str, Any]:
    """Genera y reserva el lead justo antes de ejecutar cada fila.

    - Envío real normal: usa únicamente el banco autorizado del país.
    - Dry run: Ollama puede proponer un número por caso para cualquier país
      configurado; Python valida estructura y duplicados.
    - Envío sintético real explícito: además exige validación libphonenumber.
    - Si Ollama no está disponible, se conserva el generador local como respaldo.
    """

    if require_authorized_phone:
        return lead_service.reserve(country, require_authorized_phone=True)

    normalized_country = lead_service._normalize(country)
    country_label = country.strip()
    rule = lead_service.PHONE_FORMATS.get(normalized_country)

    if rule is None:
        return lead_service.reserve(country, require_authorized_phone=False)

    ai_service = AIService(settings)
    us_aliases = {"usa", "united states", "estados unidos", "global"}

    for attempt in range(1, 7):
        with get_connection(settings.database_path) as connection:
            used = {
                str(row[0])
                for row in connection.execute("SELECT phone FROM test_leads")
            }

        prompt = _ollama_phone_prompt(
            lead_service,
            country_label,
            used,
            attempt,
        )

        try:
            completion = await ai_service.generate(
                "ollama",
                prompt,
                system_instruction=(
                    "Eres un generador estricto de datos sintéticos para pruebas QA. "
                    "Nunca agregues explicaciones. Respeta exactamente la longitud, "
                    "el prefijo y la lista de números prohibidos."
                ),
                model=settings.ollama_local_model,
                local=True,
            )
            phone = _extract_ai_phone_candidate(completion.text)
        except Exception as error:
            logger.warning(
                "Ollama no pudo generar teléfono para %s en intento %s: %s",
                country_label,
                attempt,
                error,
            )
            continue

        if normalized_country in us_aliases:
            structurally_valid = _is_safe_us_synthetic_phone(phone)
        else:
            structurally_valid = _phone_matches_country_rule(
                lead_service,
                country_label,
                phone,
            )

        if not structurally_valid:
            logger.warning(
                "Ollama propuso un teléfono fuera de la regla de %s: %s",
                country_label,
                phone,
            )
            continue

        if phone in used:
            logger.info(
                "Ollama repitió %s para %s; se solicitará otro.",
                phone,
                country_label,
            )
            continue

        if (
            lead_service.allow_synthetic_real_phones
            and not lead_service._is_valid_generated_phone(
                phone,
                normalized_country,
            )
        ):
            logger.warning(
                "Ollama propuso un teléfono que no supera libphonenumber para %s: %s",
                country_label,
                phone,
            )
            continue

        reserved = _reserve_specific_test_phone(
            settings,
            lead_service,
            country_label,
            phone,
        )
        if reserved is None:
            continue

        logger.info(
            "Ollama generó y reservó %s para un caso de %s.",
            phone,
            country_label,
        )
        return reserved

    if normalized_country in us_aliases:
        return _fallback_us_test_lead(
            settings,
            lead_service,
            country_label,
            normalized_country,
        )

    return lead_service.reserve(country, require_authorized_phone=False)


@router.get("/runtime")
def backend_runtime() -> dict:
    """Permite a Electron reconocer su proceso, sin exponer secretos."""
    return {"instance_id": os.environ.get("QA_BACKEND_INSTANCE", ""), "pid": os.getpid()}


@router.post("/bots/utel-inconcert/spreadsheet-preview")
async def preview_bot_spreadsheet(file: UploadFile = File(...)) -> dict:
    """Analiza hojas Excel y propone un mapeo flexible para el Bot."""

    if not (file.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Comparte un archivo Excel con extensión .xlsx.")
    try:
        return BotSpreadsheetService().preview(await file.read(), file.filename or "archivo.xlsx")
    except asyncio.CancelledError:
        job.update({"status": "CANCELLED", "finished_at": datetime.now().isoformat(timespec="seconds"), "summary": "Lote detenido por el usuario."})
        raise
    except Exception as error:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"No fue posible analizar el Excel: {error}") from error


async def _run_utel_batch_job(application, job_id: str, content: bytes, filename: str, raw_config: dict, mapping: dict[str, str]) -> None:
    """Ejecuta las filas seleccionadas y escribe URL LEAD en una copia del Excel."""

    settings = application.state.settings
    job = application.state.utel_batch_jobs[job_id]
    batch_size = max(1, int(settings.batch_size))
    batch_pause_seconds = max(0, int(settings.batch_delay_seconds))
    results: list[dict[str, Any]] = []
    logger.info(
        "Lote %s en tandas de %s filas, sin pausa interna y con %ss entre tandas",
        job_id,
        batch_size,
        batch_pause_seconds,
    )
    try:
        batch_dry_run = _batch_dry_run(raw_config)
        is_leads_deploy = raw_config.get("automation_module") == "leads_deploy"
        service_cls = LeadsDeploySpreadsheetService if is_leads_deploy else BotSpreadsheetService
        runner_cls = LeadsDeployRunner if is_leads_deploy else UtelInconcertRunner
        service = service_cls(settings.program_catalog_path)
        rows = service.rows_for_mapping(content, mapping)
        selected_rows = {
            (str(item.get("sheet")), int(item.get("row_number")))
            for item in mapping.get("selected_rows", [])
            if item.get("sheet") and item.get("row_number") is not None
        }
        selected_sheet = mapping.get("selected_sheet")
        selected_row_number = mapping.get("selected_row_number")
        if selected_rows:
            rows = [row for row in rows if (row["sheet"], row["row_number"]) in selected_rows]
        elif selected_sheet and selected_row_number is not None:
            rows = [row for row in rows if row["sheet"] == selected_sheet and row["row_number"] == int(selected_row_number)]
        if not rows:
            raise ValueError(
                "No se encontraron casos Leads Deploy con País, Nivel y Formulario. "
                "La columna Activo de Test no es obligatoria; las URLs se toman del catálogo interno."
                if is_leads_deploy
                else "No se encontraron filas con Programa/Nivel y URL usando las columnas seleccionadas."
            )
        needs_inconcert = any(
            not _is_balanceador_url(row.get("lead_origin_url", ""))
            for row in rows
        )
        if not batch_dry_run and needs_inconcert:
            # InConcert se valida antes del primer clic. Los lotes cuyo origen
            # es exclusivamente Balanceador reutilizan la sesión chrome-qa y no
            # deben exigir credenciales de un CRM que nunca van a consultar.
            crm_preflight = runner_cls(settings)
            if not crm_preflight.has_inconcert_credentials():
                raise ValueError(
                    "No se inició ningún envío: faltan credenciales de InConcert. "
                    "Configura INCONCERT_USERNAME/INCONCERT_PASSWORD o CRM_USERNAME/CRM_PASSWORD en .env."
                )
        workflow_mode = rows[0].get("workflow_mode", "product_release")
        job["workflow_mode"] = workflow_mode
        base_config = dict(raw_config)
        base_config.update({
            "utel_url": rows[0]["utel_url"],
            "program_name": rows[0]["program_name"],
            "dry_run": batch_dry_run,
            "workflow_mode": workflow_mode,
            "source_filename": filename,
        })
        # Prepara y valida todas las configuraciones antes de reservar datos o
        # abrir formularios. Los flags internos nunca se heredan del cliente.
        prepared_rows: list[tuple[dict[str, Any], UtelQaConfig]] = []
        for row in rows:
            row_config = dict(base_config)
            skip_preselected_fields = _is_new_products_scope(
                row.get("sheet", ""),
                filename,
            )
            if row.get("workflow_mode") == "form_validation" and not row.get("country"):
                raise ValueError(
                    f"La fila {row['row_number']} no tiene pais en la columna Locale/Country."
                )
            row_country = (
                row["country"]
                if row.get("workflow_mode") == "form_validation"
                else row.get("country") or raw_config.get("country") or "Ecuador"
            )
            row_country = service.effective_country(row_country, row["level"], row["utel_url"])
            navigation = (
                service.deploy_navigation_plan(row["level"], row_country)
                if row.get("workflow_mode") == "form_validation"
                else {
                    "modality": (
                        row.get("modality")
                        or raw_config.get("modality")
                        or "En linea"
                    ),
                    "level": (
                        row.get("level")
                        or raw_config.get("level")
                        or "Licenciatura"
                    ),
                    "navigation_modality": "",
                    "navigation_level": "",
                    "navigation_sublevel": "",
                }
            )
            catalog_program = None
            # El catálogo oficial se activa para Leads Deploy (identificado por
            # su columna Url Origen Lead) y no altera Excels genéricos antiguos.
            use_official_catalog = bool(
                row.get("lead_origin_url")
                or "leads deploy" in filename.casefold()
            )
            if not row["program_name"] and use_official_catalog:
                catalog_program = service.choose_catalog_program(
                    row_country,
                    row["level"],
                    navigation["modality"],
                    settings.database_path,
                )
            lead_origin_url = row.get("lead_origin_url", "")
            uses_balanceador = _is_balanceador_url(lead_origin_url)
            row_config.update({
                "utel_url": catalog_program["url"] if catalog_program else row["utel_url"],
                "program_name": catalog_program["text"] if catalog_program else row["program_name"],
                "program_selection_strategy": "exact_match" if (row["program_name"] or catalog_program) else "first",
                "modality": navigation["modality"],
                "level": navigation["level"],
                "navigation_modality": navigation["navigation_modality"],
                "navigation_level": navigation["navigation_level"],
                "navigation_sublevel": navigation["navigation_sublevel"],
                "country": row_country,
                "form_type": (
                    row.get("form_type")
                    or raw_config.get("form_type")
                    or "lateral"
                ),
                "lead_origin_url": lead_origin_url,
                # El país de esta fila manda: nunca heredar el CRM de otra fila.
                "inconcert_url": (
                    row.get("lead_origin_url")
                    or service.default_inconcert_url(row_country)
                    or row["inconcert_url"]
                ),
                "workflow_mode": row.get("workflow_mode", "product_release"),
                "name": f"{raw_config.get('name', 'QA UTEL')} - {row.get('test_case') or row['program_name'] or row['level']}",
                "defer_crm_verification": False,
                "verification_only": False,
                "skip_preselected_fields": skip_preselected_fields,
                # Cloudflare reconoce mejor el perfil persistente de Chrome que
                # un Chromium aislado nuevo. Balanceador se abre visible para
                # permitir completar un desafío legítimo si vuelve a solicitarlo.
                "browser": "chrome" if (uses_balanceador and not batch_dry_run) else row_config.get("browser", "chromium"),
                "headless": False if (uses_balanceador and not batch_dry_run) else row_config.get("headless", True),
            })
            prepared_rows.append((row, UtelQaConfig.model_validate(row_config)))

        lead_service = TestLeadService(
            settings.database_path,
            settings.authorized_test_phones()
            if not batch_dry_run and not settings.utel_allow_synthetic_real_phones
            else {},
            allow_synthetic_real_phones=(
                not batch_dry_run and settings.utel_allow_synthetic_real_phones
            ),
        )
        if not batch_dry_run and not settings.utel_allow_synthetic_real_phones:
            # Primero se valida localmente que cada fila tenga un número real,
            # válido y disponible. No se abre CRM ni UTEL con un banco incompleto.
            lead_service.validate_authorized_capacity(
                [config.country for _, config in prepared_rows]
            )

        if not batch_dry_run:
            # Se valida login y acceso a Contactos para cada CRM distinto antes
            # del primer clic. Así una contraseña vencida o una caída regional
            # no deja un lote entero sin posibilidad de conciliación.
            job["phase"] = "CRM: validando acceso antes de enviar"
            checked_crm_urls: set[str] = set()
            for row, preflight_config in prepared_rows:
                if job.get("cancel_requested"):
                    break
                if _is_balanceador_url(preflight_config.lead_origin_url):
                    # El Balanceador se valida al consultar el lead; no se
                    # intenta abrir InConcert cuando el Excel ya indicó el origen.
                    continue
                if preflight_config.inconcert_url in checked_crm_urls:
                    continue
                job.update({
                    "current_program": f"Validación CRM: {preflight_config.country}",
                    "current_row": row["row_number"],
                })
                await runner_cls(settings).preflight_inconcert(preflight_config)
                checked_crm_urls.add(preflight_config.inconcert_url)

        verification_queue = []
        temporary_block_queue = []
        job["phase"] = "UTEL: enviando formularios"
        for index, (row, prepared_config) in enumerate(prepared_rows, 1):
            # La detención es cooperativa: no inicia otra fila, pero jamás
            # interrumpe una fila que pudiera estar justo después del clic.
            if job.get("cancel_requested"):
                break

            job.update({
                "phase": f"Generando datos de prueba para fila {row['row_number']}",
                "current_program": row.get("test_case") or row["program_name"] or row["level"],
                "current_row": row["row_number"],
                "last_error": "",
            })

            try:
                lead = await _reserve_lead_for_case(
                    settings,
                    lead_service,
                    prepared_config.country,
                    require_authorized_phone=(
                        not batch_dry_run
                        and not settings.utel_allow_synthetic_real_phones
                    ),
                )
            except ValueError as error:
                failed_result = {
                    "status": "FAIL",
                    "summary": str(error),
                    "dry_run": batch_dry_run,
                    "country": prepared_config.country,
                    "level": prepared_config.level,
                    "modality": prepared_config.modality,
                    "form_type": prepared_config.form_type,
                    "lead_name": "",
                    "lead_email": "",
                    "lead_phone": "",
                    "lead_url": None,
                    "selected_program_name": prepared_config.program_name,
                    "utel_submission_attempted": False,
                    "utel_submission": "failed",
                    "utel_submission_message": str(error),
                    "inconcert_login": "skipped",
                    "lead_found": "skipped",
                    "conversion_found": "skipped",
                    "stages": [{
                        "step_number": 0,
                        "stage": "startup",
                        "status": "FAIL",
                        "message": str(error),
                        "selector": None,
                        "url": None,
                        "screenshot": None,
                    }],
                    "screenshots": [],
                }
                results.append({"row": row, "result": failed_result})
                _save_utel_batch_report(
                    settings, job_id, filename, content, mapping, results
                )
                counts = _utel_batch_counts(results)
                job.update({
                    "completed": len(results),
                    **counts,
                    "last_error": str(error),
                    "results": results,
                    "download_url": f"/api/bots/utel-inconcert/batch/{job_id}/download",
                })
                continue

            config = prepared_config.model_copy(
                update={"lead": prepared_config.lead.model_copy(update=lead)}
            )
            if not config.dry_run:
                # Flujo secuencial por fila: el runner envía el formulario y
                # consulta inmediatamente el CRM indicado antes de continuar.
                config = config.model_copy(
                    update={"defer_crm_verification": False, "verification_only": False}
                )
            job.update({
                "current_program": row.get("test_case") or row["program_name"] or row["level"],
                "current_row": row["row_number"],
                "current_lead_name": config.lead.name,
                "current_lead_email": config.lead.email,
                "current_lead_phone": config.lead.phone,
                "last_error": "",
            })
            result_index: int | None = None
            if not config.dry_run:
                # Checkpoint preventivo: si el proceso se cierra en la ventana
                # del clic, el Excel conserva el email para buscarlo en CRM y
                # la fila queda bloqueada para reintento automático.
                provisional_result = {
                    "status": "FAIL",
                    "summary": (
                        "Ejecución iniciada y estado final aún desconocido. "
                        "Si el backend se interrumpe, buscar este email en CRM antes de reenviar."
                    ),
                    "dry_run": False,
                    "country": config.country,
                    "level": config.level,
                    "modality": config.modality,
                    "form_type": config.form_type,
                    "lead_name": config.lead.name,
                    "lead_email": config.lead.email,
                    "lead_phone": config.lead.phone,
                    "lead_url": None,
                    "selected_program_name": config.program_name,
                    "utel_submission_attempted": None,
                    "utel_submission": "pending",
                    "utel_submission_message": (
                        "Estado desconocido; no reenviar automáticamente sin consultar CRM."
                    ),
                    "inconcert_login": "skipped",
                    "lead_found": "pending",
                    "conversion_found": "pending",
                    "stages": [],
                    "screenshots": [],
                }
                results.append({"row": row, "result": provisional_result})
                result_index = len(results) - 1
                _save_utel_batch_report(settings, job_id, filename, content, mapping, results)
                job["download_url"] = f"/api/bots/utel-inconcert/batch/{job_id}/download"
            retry_notes: list[str] = []
            attempts_used = 0
            for retry_number in range(3):
                attempts_used += 1
                result = await runner_cls(settings).run(config)
                serializable_result = {
                    **result,
                    "stages": [stage.model_dump() for stage in result["stages"]],
                }
                if not _is_support_rejection(serializable_result):
                    break
                if retry_number == 2:
                    retry_notes.append("Se agotaron los 3 intentos automáticos.")
                    break
                try:
                    retry_lead = await _reserve_lead_for_case(
                        settings,
                        lead_service,
                        config.country,
                        require_authorized_phone=(
                            not batch_dry_run
                            and not settings.utel_allow_synthetic_real_phones
                        ),
                    )
                except ValueError as error:
                    retry_notes.append(str(error))
                    break
                retry_notes.append(
                    f"Rechazo de UTEL; se probó un teléfono distinto (intento {retry_number + 2}/3)."
                )
                config = config.model_copy(
                    update={"lead": config.lead.model_copy(update=retry_lead)}
                )
                job.update({
                    "current_lead_name": config.lead.name,
                    "current_lead_email": config.lead.email,
                    "current_lead_phone": config.lead.phone,
                    "last_error": "Reintentando rechazo explícito de UTEL con otro teléfono.",
                })
            if retry_notes:
                serializable_result["retry_attempts"] = attempts_used - 1
                serializable_result["retry_history"] = retry_notes
                if _is_support_rejection(serializable_result):
                    serializable_result["summary"] = (
                        f"{serializable_result.get('summary', '')} "
                        f"UTEL rechazó el formulario después de {attempts_used} intentos; requiere ejecución manual."
                    ).strip()
                    serializable_result["utel_submission_message"] = (
                        f"{serializable_result.get('utel_submission_message', '')} "
                        "Se agotaron los 3 intentos automáticos; realiza este caso manualmente."
                    ).strip()
            if result_index is None:
                results.append({"row": row, "result": serializable_result})
                result_index = len(results) - 1
            else:
                results[result_index] = {"row": row, "result": serializable_result}
            # El reporte se actualiza fila por fila para no perder los enlaces
            # ya obtenidos si el backend se reinicia o el lote se detiene.
            _save_utel_batch_report(settings, job_id, filename, content, mapping, results)
            job["download_url"] = f"/api/bots/utel-inconcert/batch/{job_id}/download"
            if (
                not config.dry_run
                and _is_post_submit_crm_retry_candidate(serializable_result)
            ):
                # Después de POST /api/forms cualquier fallo de InConcert o
                # Balanceador puede reintentarse como verification_only. Nunca
                # se vuelve a ejecutar UTEL ni se genera otro lead.
                verification_queue.append((result_index, config))
            elif (
                _is_temporary_access_block(serializable_result)
                or _is_safe_visible_retry_candidate(serializable_result)
            ):
                # Cualquier fallo ocurrido antes del clic puede reintentarse una
                # vez de forma segura. El segundo intento usa Chrome visible para
                # reducir diferencias de renderizado, timing y bloqueos anti-bot,
                # sin importar el país de la fila.
                temporary_block_queue.append((result_index, config))
            failed_stage = next((stage for stage in serializable_result["stages"] if stage["status"] == "FAIL"), None)
            counts = _utel_batch_counts(results)
            job.update({
                "completed": len(results),
                **counts,
                "current_program": row.get("test_case") or row["program_name"] or row["level"],
                "current_row": row["row_number"],
                "last_error": failed_stage["message"] if failed_stage else "",
                "results": results,
            })
            if job.get("cancel_requested"):
                break
            if index % batch_size == 0:
                completed_batch = index // batch_size
                # El checkpoint ya contiene esta tanda y todas las anteriores.
                # La misma URL sirve siempre el Excel acumulado más reciente.
                job.update({
                    "completed_batches": completed_batch,
                    "last_checkpoint_rows": index,
                    "summary": (
                        f"Tanda {completed_batch} completada: Excel acumulado listo "
                        f"con {index} filas procesadas."
                    ),
                })
                if index < len(rows):
                    job["phase"] = (
                        f"Tanda {completed_batch} completada · pausa de "
                        f"{batch_pause_seconds} segundos"
                    )
                    if batch_pause_seconds > 0:
                        await asyncio.sleep(batch_pause_seconds)
                    if job.get("cancel_requested"):
                        break
                    job["phase"] = f"UTEL: procesando tanda {completed_batch + 1}"

        if temporary_block_queue and not job.get("cancel_requested"):
            job["phase"] = "UTEL: reintentando casos seguros en navegador visible"
            for result_index, blocked_config in temporary_block_queue:
                row = results[result_index]["row"]
                job.update({
                    "current_program": row.get("test_case") or row["program_name"] or row["level"],
                    "current_row": row["row_number"],
                    "current_lead_name": blocked_config.lead.name,
                    "current_lead_email": blocked_config.lead.email,
                    "current_lead_phone": blocked_config.lead.phone,
                    "last_error": "Reintentando fila previa al envío en Chrome visible.",
                })
                # Un bloqueo UTEL antes del clic es seguro para reintentar.
                # Se deja enfriar la sesión y se usa el perfil persistente de
                # Chrome para reducir bloqueos repetidos del sitio.
                await asyncio.sleep(20)
                retry_config = blocked_config.model_copy(
                    update={"browser": "chrome", "headless": False}
                )
                retry_result = await runner_cls(settings).run(retry_config)
                serializable_retry = {
                    **retry_result,
                    "stages": [stage.model_dump() for stage in retry_result["stages"]],
                    "temporary_block_retry_attempted": True,
                }
                results[result_index]["result"] = serializable_retry
                if (
                    not blocked_config.dry_run
                    and _is_post_submit_crm_retry_candidate(serializable_retry)
                ):
                    verification_queue.append((result_index, retry_config))
                _save_utel_batch_report(settings, job_id, filename, content, mapping, results)
                counts = _utel_batch_counts(results)
                job.update({"completed": len(results), **counts, "results": results})

        if verification_queue:
            job["phase"] = "CRM: reintentando verificaciones bloqueadas"
            logger.info(
                "Lote %s reintentando verificaciones bloqueadas sin pausa entre consultas",
                job_id,
            )
            for result_index, submitted_config in sorted(
                verification_queue, key=lambda item: item[1].country.casefold()
            ):
                verify_config = submitted_config.model_copy(
                    update={"defer_crm_verification": False, "verification_only": True}
                )
                job.update({
                    "current_program": results[result_index]["row"].get("test_case") or results[result_index]["row"]["program_name"] or results[result_index]["row"]["level"],
                    "current_row": results[result_index]["row"]["row_number"],
                    "current_lead_name": verify_config.lead.name,
                    "current_lead_email": verify_config.lead.email,
                    "current_lead_phone": verify_config.lead.phone,
                    "last_error": "",
                })
                # Esta fase es verification_only: puede cambiar de navegador
                # sin riesgo de volver a enviar UTEL.
                verify_config = verify_config.model_copy(
                    update={"browser": "chrome", "headless": False}
                )
                verification = await runner_cls(settings).run(verify_config)
                serializable_verification = {**verification, "stages": [stage.model_dump() for stage in verification["stages"]]}
                submission = results[result_index]["result"]
                results[result_index]["result"] = _merge_utel_and_crm_results(
                    submission,
                    serializable_verification,
                )
                results[result_index]["result"]["temporary_block_retry_attempted"] = True
                # Sustituye el checkpoint con el enlace CRM confirmado.
                _save_utel_batch_report(settings, job_id, filename, content, mapping, results)
                counts = _utel_batch_counts(results)
                job.update({
                    "completed": len(results),
                    **counts,
                    "results": results,
                })

        _save_utel_batch_report(settings, job_id, filename, content, mapping, results)
        counts = _utel_batch_counts(results)
        cancel_requested = bool(job.get("cancel_requested"))
        final_status = (
            "CANCELLED"
            if cancel_requested
            else ("PASS" if counts["failed"] == 0 and counts["pending"] == 0 else "FAIL")
        )
        job.update({
            "status": final_status,
            "phase": "Lote completado" if not cancel_requested else job.get("phase"),
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "download_url": (
                f"/api/bots/utel-inconcert/batch/{job_id}/download" if results else None
            ),
            "results": results,
            **counts,
        })
        if cancel_requested:
            job["summary"] = (
                "Detención segura completada: no se iniciaron nuevas filas y "
                "todos los envíos ya iniciados fueron conciliados sin reenviar."
            )
    except asyncio.CancelledError:
        # Detención inmediata solicitada desde la interfaz. El checkpoint previo
        # conserva el correo de la fila activa para evitar un reenvío accidental.
        _save_utel_batch_report(settings, job_id, filename, content, mapping, results)
        counts = _utel_batch_counts(results)
        possibly_submitted = any(
            not item.get("result", {}).get("dry_run", False)
            and item.get("result", {}).get("utel_submission_attempted") is not False
            for item in results
        )
        summary = (
            "Ejecución detenida. La fila activa pudo quedar entre el clic y la "
            "confirmación; verifica el correo registrado en CRM antes de reintentar."
            if possibly_submitted
            else "Ejecución detenida antes de confirmar un envío UTEL."
        )
        job.update({
            "status": "CANCELLED",
            "phase": "Ejecución detenida",
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "summary": summary,
            "download_url": (
                f"/api/bots/utel-inconcert/batch/{job_id}/download"
                if results
                else None
            ),
            "results": results,
            **counts,
        })
        return
    except Exception as error:  # noqa: BLE001
        logger.exception("No se pudo completar el lote UTEL/InConcert %s", job_id)
        _save_utel_batch_report(settings, job_id, filename, content, mapping, results)
        job.update({"status": "FAIL", "finished_at": datetime.now().isoformat(timespec="seconds"), "summary": str(error)})


@router.post("/bots/utel-inconcert/batch-run", status_code=202)
async def run_utel_batch(request: Request, file: UploadFile = File(...), config: str = Form(...), mapping: str = Form(...)) -> dict:
    """Inicia la ejecución de todas las filas del Excel con un mapeo elegido."""

    if not (file.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Comparte un archivo Excel con extensión .xlsx.")
    try:
        raw_config = json.loads(config)
        batch_dry_run = _batch_dry_run(raw_config)
        selected_mapping = json.loads(mapping)
        is_leads_deploy = raw_config.get("automation_module") == "leads_deploy"
        if is_leads_deploy:
            if not all(selected_mapping.get(key) for key in ("country", "level", "form_type")):
                raise ValueError(
                    "Leads Deploy requiere las columnas País, Nivel y Formulario. "
                    "Activo de Test/URL no es obligatorio porque se usa el catálogo interno."
                )
            preview_service = LeadsDeploySpreadsheetService()
        else:
            if not (selected_mapping.get("program_name") or selected_mapping.get("level")) or not selected_mapping.get("utel_url"):
                raise ValueError("Selecciona una columna de Programa o Nivel, además de la columna URL.")
            preview_service = BotSpreadsheetService()
        content = await file.read()
        preview_rows = preview_service.rows_for_mapping(content, selected_mapping)
        selected_rows = {
            (str(item.get("sheet")), int(item.get("row_number")))
            for item in selected_mapping.get("selected_rows", [])
            if item.get("sheet") and item.get("row_number") is not None
        }
        selected_sheet = selected_mapping.get("selected_sheet")
        selected_row_number = selected_mapping.get("selected_row_number")
        if selected_rows:
            preview_rows = [row for row in preview_rows if (row["sheet"], row["row_number"]) in selected_rows]
        elif selected_sheet and selected_row_number is not None:
            preview_rows = [row for row in preview_rows if row["sheet"] == selected_sheet and row["row_number"] == int(selected_row_number)]
        if not preview_rows:
            raise ValueError("No se encontraron filas válidas con el mapeo seleccionado.")
    except (ValueError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    job_id = uuid4().hex
    request.app.state.utel_batch_jobs[job_id] = {
        "job_id": job_id,
        "status": "RUNNING",
        "total": len(preview_rows),
        "completed": 0,
        "success": 0,
        "failed": 0,
        "pending": 0,
        "phase": "UTEL: preparando envíos",
        "batch_size": max(1, int(request.app.state.settings.batch_size)),
        "completed_batches": 0,
        "last_checkpoint_rows": 0,
        "download_url": None,
        "workflow_mode": preview_rows[0].get("workflow_mode", "product_release"),
        "dry_run": batch_dry_run,
        "cancel_requested": False,
    }
    task = asyncio.create_task(_run_utel_batch_job(request.app, job_id, content, file.filename or "resultado.xlsx", raw_config, selected_mapping))
    request.app.state.bot_tasks[job_id] = task
    task.add_done_callback(lambda _: request.app.state.bot_tasks.pop(job_id, None))
    return request.app.state.utel_batch_jobs[job_id]


@router.get("/bots/utel-inconcert/batch/{job_id}")
async def utel_batch_status(request: Request, job_id: str) -> dict:
    job = request.app.state.utel_batch_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="El lote no existe o ya no está disponible.")
    return job


@router.post("/bots/utel-inconcert/batch/{job_id}/cancel")
async def cancel_utel_batch(request: Request, job_id: str) -> dict:
    job = request.app.state.utel_batch_jobs.get(job_id)
    task = request.app.state.bot_tasks.get(job_id)
    if job is None or task is None or task.done():
        raise HTTPException(status_code=404, detail="El lote ya terminó o no existe.")

    job.update({
        "cancel_requested": True,
        "phase": "Deteniendo ejecución y cerrando navegador",
        "summary": "Detención inmediata solicitada por el usuario.",
    })
    task.cancel()
    # Cede el control para que el worker registre CANCELLED antes del siguiente poll.
    await asyncio.sleep(0)
    return job


@router.get("/bots/utel-inconcert/batch/{job_id}/download")
async def download_utel_batch(request: Request, job_id: str) -> FileResponse:
    output_dir = request.app.state.settings.storage_dir / "reports" / "bot"
    path = next(output_dir.glob(f"{job_id}_*.xlsx"), None)
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="El Excel todavía no está disponible.")
    return FileResponse(path, filename=path.name, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@router.post("/weekly-auto/run", response_model=WeeklyAutoJobResponse, status_code=202)
async def run_weekly_auto(request: Request, config: WeeklyAutoConfig) -> dict:
    """Inicia la captura semanal sin bloquear la interfaz."""

    if not config.urls and not config.use_default_urls:
        raise HTTPException(status_code=400, detail="Debes indicar URLs o activar el uso de URLs por defecto.")
    job_id = uuid4().hex
    started_at = datetime.now().isoformat(timespec="seconds")
    request.app.state.weekly_auto_jobs[job_id] = {
        "job_id": job_id,
        "name": config.name,
        "status": "RUNNING",
        "started_at": started_at,
        "finished_at": None,
        "duration_seconds": None,
        "total_urls": None,
        "completed": 0,
        "successful": 0,
        "failed": 0,
        "skipped": 0,
        "current_url": None,
        "current_index": None,
        "summary": "Weekly Auto ejecutándose en segundo plano.",
        "result": None,
    }
    task = asyncio.create_task(_run_weekly_auto_job(request.app, job_id, config))
    request.app.state.bot_tasks[job_id] = task
    task.add_done_callback(lambda _: request.app.state.bot_tasks.pop(job_id, None))
    return request.app.state.weekly_auto_jobs[job_id]


@router.get("/weekly-auto/runs/{job_id}", response_model=WeeklyAutoJobResponse)
async def weekly_auto_status(request: Request, job_id: str) -> dict:
    """Consulta el estado de la corrida semanal."""

    job = request.app.state.weekly_auto_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="La corrida semanal no existe o ya no está disponible.")
    return job


@router.post("/weekly-auto/runs/{job_id}/cancel")
async def cancel_weekly_auto_run(request: Request, job_id: str) -> dict:
    """Cancela una corrida semanal en curso."""

    job = request.app.state.weekly_auto_jobs.get(job_id)
    task = request.app.state.bot_tasks.get(job_id)
    if job is None or task is None or task.done():
        raise HTTPException(status_code=404, detail="La corrida ya terminó o no existe.")
    job.update({"status": "CANCELLED", "finished_at": datetime.now().isoformat(timespec="seconds"), "summary": "Corrida cancelada por el usuario."})
    task.cancel()
    return job

logger = get_logger()


def dashboard_service(request: Request) -> DashboardService:
    """Obtiene el servicio a partir de la configuración guardada en la aplicación."""

    return DashboardService(request.app.state.settings.database_path)


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Permite a Electron saber si el backend local está disponible."""

    return HealthResponse(
        status="ok",
        service="qa-automation-backend",
        timestamp=datetime.now().isoformat(timespec="seconds"),
    )


@router.get("/ai/providers", response_model=AIProvidersResponse)
def ai_providers(request: Request) -> dict:
    """Indica qué proveedores de IA están configurados sin revelar secretos."""

    return {"providers": AIService(request.app.state.settings).provider_statuses()}


@router.post("/ai/generate", response_model=AICompletionResponse)
async def ai_generate(request: Request, payload: AICompletionRequest) -> dict:
    """Genera texto con el proveedor elegido para los módulos futuros."""

    try:
        completion = await AIService(request.app.state.settings).generate(
            payload.provider,
            payload.prompt,
            system_instruction=payload.system_instruction,
            model=payload.model,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    return {
        "provider": completion.provider,
        "model": completion.model,
        "text": completion.text,
        "usage": completion.usage,
        "rate_limits": completion.rate_limits,
    }


@router.get("/dashboard/summary", response_model=DashboardSummary)
def dashboard_summary(request: Request) -> dict:
    """Entrega las tarjetas y última ejecución del dashboard."""

    logger.info("Consultando resumen del dashboard")
    return dashboard_service(request).summary()


@router.get("/executions", response_model=ExecutionListResponse)
def executions(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
) -> dict:
    """Entrega el historial paginado de forma sencilla para la Fase 1."""

    items = dashboard_service(request).history(limit)
    return {"items": items, "total": len(items)}


async def _run_bot_job(application, job_id: str, config: BotConfig) -> None:
    """Ejecuta el bot fuera de la solicitud HTTP y actualiza su estado."""

    settings = application.state.settings
    try:
        logger.info("Iniciando bot en segundo plano: %s (%s)", config.name, job_id)
        result = await BotRunner(settings).run(config)
        serializable_result = {
            **result,
            "steps": [step.model_dump() for step in result["steps"]],
        }
        ExecutionRepository(settings.database_path).create_execution(
            {
                "automation_type": "generic_bot",
                "name": config.name,
                "status": "SUCCESS" if result["status"] == "PASS" else "FAIL",
                "started_at": result["started_at"],
                "finished_at": result["finished_at"],
                "duration_seconds": result["duration_seconds"],
                "summary": result["summary"],
                "error_message": None if result["status"] == "PASS" else result["summary"],
                "evidence_json": json.dumps(serializable_result, ensure_ascii=False),
                "created_at": result["finished_at"],
            }
        )
        application.state.bot_jobs[job_id] = {
            "job_id": job_id,
            "name": config.name,
            "status": result["status"],
            "started_at": result["started_at"],
            "finished_at": result["finished_at"],
            "duration_seconds": result["duration_seconds"],
            "summary": result["summary"],
            "result": serializable_result,
        }
        logger.info("Bot finalizado: %s - %s", config.name, result["status"])
    except asyncio.CancelledError:
        logger.info("Bot cancelado durante el cierre del backend: %s (%s)", config.name, job_id)
        raise
    except Exception as error:  # noqa: BLE001 - el estado se devuelve a la interfaz
        logger.exception("No se pudo completar el bot %s", config.name)
        now = datetime.now().isoformat(timespec="seconds")
        application.state.bot_jobs[job_id] = {
            "job_id": job_id,
            "name": config.name,
            "status": "FAIL",
            "started_at": application.state.bot_jobs[job_id]["started_at"],
            "finished_at": now,
            "duration_seconds": None,
            "summary": str(error),
            "result": None,
        }


@router.post("/bots/run", response_model=BotStartResponse, status_code=202)
async def run_bot(request: Request, config: BotConfig) -> dict:
    """Inicia un flujo en segundo plano y devuelve el control inmediatamente."""

    job_id = uuid4().hex
    started_at = datetime.now().isoformat(timespec="seconds")
    request.app.state.bot_jobs[job_id] = {
        "job_id": job_id,
        "name": config.name,
        "status": "RUNNING",
        "started_at": started_at,
        "finished_at": None,
        "duration_seconds": None,
        "summary": "El bot está ejecutándose en segundo plano.",
        "result": None,
    }
    task = asyncio.create_task(_run_bot_job(request.app, job_id, config))
    request.app.state.bot_tasks[job_id] = task
    task.add_done_callback(lambda _: request.app.state.bot_tasks.pop(job_id, None))
    return {"job_id": job_id, "name": config.name, "status": "RUNNING", "started_at": started_at}


@router.get("/bots/runs/{job_id}", response_model=BotJobResponse)
async def bot_run_status(request: Request, job_id: str) -> dict:
    """Consulta el progreso o resultado de un bot en segundo plano."""

    job = request.app.state.bot_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="La ejecución del bot no existe o ya no está disponible.")
    return job


async def _run_utel_inconcert_job(application, job_id: str, config: UtelQaConfig) -> None:
    """Ejecuta el flujo especializado UTEL/InConcert en segundo plano."""

    settings = application.state.settings
    try:
        logger.info("Iniciando flujo UTEL/InConcert: %s (%s)", config.name, job_id)
        retry_notes: list[str] = []
        attempts_used = 0
        for retry_number in range(3):
            attempts_used += 1
            result = await UtelInconcertRunner(settings).run(
                config,
                should_stop=lambda: bool(
                    application.state.utel_inconcert_jobs.get(job_id, {}).get(
                        "cancel_requested"
                    )
                ),
            )
            serializable_result = {
                **result,
                "stages": [stage.model_dump() for stage in result["stages"]],
            }
            if not _is_support_rejection(serializable_result):
                break
            if retry_number == 2:
                retry_notes.append("Se agotaron los 3 intentos automáticos.")
                break
            try:
                retry_service = TestLeadService(
                    settings.database_path,
                    settings.authorized_test_phones()
                    if not settings.utel_allow_synthetic_real_phones
                    else {},
                    allow_synthetic_real_phones=settings.utel_allow_synthetic_real_phones,
                )
                retry_lead = retry_service.reserve(
                    config.country,
                    require_authorized_phone=not settings.utel_allow_synthetic_real_phones,
                )
            except ValueError as error:
                retry_notes.append(str(error))
                break
            retry_notes.append(
                f"Rechazo de UTEL; se probó un teléfono distinto (intento {retry_number + 2}/3)."
            )
            config = config.model_copy(
                update={"lead": config.lead.model_copy(update=retry_lead)}
            )
        if retry_notes:
            serializable_result["retry_attempts"] = attempts_used - 1
            serializable_result["retry_history"] = retry_notes
            if _is_support_rejection(serializable_result):
                serializable_result["summary"] = (
                    f"{serializable_result.get('summary', '')} "
                    f"UTEL rechazó el formulario después de {attempts_used} intentos; requiere ejecución manual."
                ).strip()
                serializable_result["utel_submission_message"] = (
                    f"{serializable_result.get('utel_submission_message', '')} "
                    "Se agotaron los 3 intentos automáticos; realiza este caso manualmente."
                ).strip()
        cancel_requested = bool(
            application.state.utel_inconcert_jobs.get(job_id, {}).get("cancel_requested")
        )
        final_summary = serializable_result["summary"]
        if cancel_requested:
            final_summary = (
                "La detención se solicitó durante la operación. La fila activa "
                f"se completó de forma segura para no perder ni duplicar el envío. {serializable_result['summary']}"
            )
        ExecutionRepository(settings.database_path).create_execution(
            {
                "automation_type": "utel_inconcert_qa",
                "name": config.name,
                "status": "SUCCESS" if result["status"] == "PASS" else "FAIL",
                "started_at": result["started_at"],
                "finished_at": result["finished_at"],
                "duration_seconds": result["duration_seconds"],
                "summary": final_summary,
                "error_message": None if result["status"] == "PASS" else result["summary"],
                "evidence_json": json.dumps(serializable_result, ensure_ascii=False),
                "created_at": result["finished_at"],
            }
        )
        application.state.utel_inconcert_jobs[job_id] = {
            "job_id": job_id,
            "name": config.name,
            "status": result["status"],
            "started_at": result["started_at"],
            "finished_at": result["finished_at"],
            "duration_seconds": result["duration_seconds"],
            "summary": final_summary,
            "result": serializable_result,
            "cancel_requested": cancel_requested,
        }
        logger.info("Flujo UTEL/InConcert finalizado: %s - %s", config.name, result["status"])
    except UtelRunCancelled as error:
        now = datetime.now().isoformat(timespec="seconds")
        current = application.state.utel_inconcert_jobs.get(job_id, {})
        application.state.utel_inconcert_jobs[job_id] = {
            "job_id": job_id,
            "name": config.name,
            "status": "CANCELLED",
            "started_at": current.get("started_at", now),
            "finished_at": now,
            "duration_seconds": None,
            "summary": str(error),
            "result": None,
            "cancel_requested": True,
        }
        logger.info("Flujo UTEL/InConcert detenido antes del envío: %s (%s)", config.name, job_id)
        return
    except asyncio.CancelledError:
        now = datetime.now().isoformat(timespec="seconds")
        current = application.state.utel_inconcert_jobs.get(job_id, {})
        application.state.utel_inconcert_jobs[job_id] = {
            "job_id": job_id,
            "name": config.name,
            "status": "CANCELLED",
            "started_at": current.get("started_at", now),
            "finished_at": now,
            "duration_seconds": None,
            "summary": (
                "Ejecución detenida por el usuario. Si el clic de envío alcanzó "
                "a generar POST /api/forms, verifica el correo en CRM antes de "
                "volver a ejecutar."
            ),
            "result": None,
            "cancel_requested": True,
        }
        logger.info("Flujo UTEL/InConcert detenido por el usuario: %s (%s)", config.name, job_id)
        return
    except Exception as error:  # noqa: BLE001 - el estado se devuelve a la interfaz
        logger.exception("No se pudo completar el flujo UTEL/InConcert %s", config.name)
        now = datetime.now().isoformat(timespec="seconds")
        application.state.utel_inconcert_jobs[job_id] = {
            "job_id": job_id,
            "name": config.name,
            "status": "FAIL",
            "started_at": application.state.utel_inconcert_jobs[job_id]["started_at"],
            "finished_at": now,
            "duration_seconds": None,
            "summary": str(error),
            "result": None,
        }


async def _run_weekly_auto_job(application, job_id: str, config: WeeklyAutoConfig) -> None:
    """Ejecuta la corrida semanal en background y actualiza el estado."""

    settings = application.state.settings
    try:
        logger.info("Iniciando Weekly Auto: %s (%s)", config.name, job_id)
        def progress(payload: dict[str, Any]) -> None:
            job = application.state.weekly_auto_jobs.get(job_id)
            if not job:
                return
            job.update(
                {
                    "current_index": payload["index"],
                    "total_urls": payload["total"],
                    "current_url": payload["url"],
                    "completed": payload["index"] - (1 if payload["status"] == "SKIPPED" else 0),
                    "successful": job.get("successful", 0) + (1 if payload["status"] == "PASS" else 0),
                    "failed": job.get("failed", 0) + (1 if payload["status"] == "FAIL" else 0),
                    "skipped": job.get("skipped", 0) + (1 if payload["status"] == "SKIPPED" else 0),
                    "summary": f"Proceso {payload['index']}/{payload['total']}: {payload['status']} - {payload['url']}",
                }
            )

        result = await WeeklyAutoRunner(settings).run(config, progress_callback=progress)
        serializable_result = result
        logger.info("Weekly Auto finalizado: %s", config.name)

        ExecutionRepository(settings.database_path).create_execution(
            {
                "automation_type": "weekly_auto",
                "name": config.name,
                "status": "SUCCESS" if result["status"] == "PASS" else "FAIL",
                "started_at": result["started_at"],
                "finished_at": result["finished_at"],
                "duration_seconds": result["duration_seconds"],
                "summary": result["summary"],
                "error_message": None if result["status"] == "PASS" else result["summary"],
                "evidence_json": json.dumps(serializable_result, ensure_ascii=False),
                "created_at": result["finished_at"],
            }
        )
        application.state.weekly_auto_jobs[job_id] = {
            "job_id": job_id,
            "name": config.name,
            "status": result["status"],
            "started_at": result["started_at"],
            "finished_at": result["finished_at"],
            "duration_seconds": result["duration_seconds"],
            "total_urls": result["total_urls"],
            "completed": result["completed"],
            "successful": result["successful"],
            "failed": result["failed"],
            "skipped": result["skipped"],
            "current_url": None,
            "current_index": None,
            "summary": result["summary"],
            "result": serializable_result,
        }
        logger.info("Weekly Auto finalizado: %s - %s", config.name, result["status"])
    except asyncio.CancelledError:
        logger.info("Weekly Auto cancelado durante ejecución: %s (%s)", config.name, job_id)
        application.state.weekly_auto_jobs[job_id] = {
            "job_id": job_id,
            "name": config.name,
            "status": "CANCELLED",
            "started_at": application.state.weekly_auto_jobs[job_id]["started_at"],
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "duration_seconds": None,
            "total_urls": None,
            "completed": 0,
            "successful": 0,
            "failed": 0,
            "skipped": 0,
            "current_url": None,
            "current_index": None,
            "summary": "Corrida cancelada por el usuario.",
            "result": None,
        }
        return
    except Exception as error:  # noqa: BLE001 - se regresa a la UI en forma de estado
        logger.exception("No se pudo completar Weekly Auto %s", config.name)
        now = datetime.now().isoformat(timespec="seconds")
        application.state.weekly_auto_jobs[job_id] = {
            "job_id": job_id,
            "name": config.name,
            "status": "FAIL",
            "started_at": application.state.weekly_auto_jobs[job_id]["started_at"],
            "finished_at": now,
            "duration_seconds": None,
            "total_urls": None,
            "completed": 0,
            "successful": 0,
            "failed": 0,
            "skipped": 0,
            "current_url": None,
            "current_index": None,
            "summary": str(error),
            "result": None,
        }


@router.post("/bots/utel-inconcert/run", response_model=BotStartResponse, status_code=202)
async def run_utel_inconcert_bot(request: Request, config: UtelQaConfig) -> dict:
    """Inicia el flujo UTEL/InConcert sin bloquear la interfaz."""

    # La API individual siempre ejecuta el ciclo completo. Estos flags son de
    # orquestación interna y no pueden quedar controlados por una petición vieja.
    config = config.model_copy(
        update={"defer_crm_verification": False, "verification_only": False}
    )
    country_crm = BotSpreadsheetService.default_inconcert_url(config.country)
    if country_crm:
        config = config.model_copy(update={"inconcert_url": country_crm})
    settings = request.app.state.settings
    try:
        generated_lead = TestLeadService(
            settings.database_path,
            settings.authorized_test_phones()
            if not config.dry_run and not settings.utel_allow_synthetic_real_phones
            else {},
            allow_synthetic_real_phones=(
                not config.dry_run and settings.utel_allow_synthetic_real_phones
            ),
        ).reserve(
            config.country,
            require_authorized_phone=(
                not config.dry_run and not settings.utel_allow_synthetic_real_phones
            ),
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    config = config.model_copy(
        update={
            "lead": config.lead.model_copy(
                update={
                    "name": generated_lead["name"],
                    "email": generated_lead["email"],
                    "phone": generated_lead["phone"],
                }
            )
        }
    )
    job_id = uuid4().hex
    started_at = datetime.now().isoformat(timespec="seconds")
    request.app.state.utel_inconcert_jobs[job_id] = {
        "job_id": job_id,
        "name": config.name,
        "status": "RUNNING",
        "started_at": started_at,
        "finished_at": None,
        "duration_seconds": None,
        "summary": "El flujo UTEL/InConcert esta ejecutandose en segundo plano.",
        "result": None,
        "cancel_requested": False,
    }
    task = asyncio.create_task(_run_utel_inconcert_job(request.app, job_id, config))
    request.app.state.bot_tasks[job_id] = task
    task.add_done_callback(lambda _: request.app.state.bot_tasks.pop(job_id, None))
    return {
        "job_id": job_id,
        "name": config.name,
        "status": "RUNNING",
        "started_at": started_at,
        "lead_email": generated_lead["email"],
        "lead_phone": generated_lead["phone"],
        "lead_name": generated_lead["name"],
    }


@router.get("/bots/utel-inconcert/runs/{job_id}", response_model=UtelQaJobResponse)
async def utel_inconcert_status(request: Request, job_id: str) -> dict:
    """Consulta el progreso o resultado del flujo UTEL/InConcert."""

    job = request.app.state.utel_inconcert_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="La ejecucion UTEL/InConcert no existe o ya no esta disponible.")
    return job


@router.post("/bots/utel-inconcert/runs/{job_id}/cancel")
async def cancel_utel_run(request: Request, job_id: str) -> dict:
    job = request.app.state.utel_inconcert_jobs.get(job_id)
    task = request.app.state.bot_tasks.get(job_id)
    if job is None or task is None or task.done():
        raise HTTPException(status_code=404, detail="La ejecución ya terminó o no existe.")

    job.update({
        "cancel_requested": True,
        "summary": "Deteniendo ejecución y cerrando navegador.",
    })
    task.cancel()
    await asyncio.sleep(0)
    return job


@router.post("/pdp/validate")
async def validate_pdp(
    request: Request,
    excel_file: UploadFile = File(...),
    docx_file: UploadFile = File(...),
) -> dict:
    """Compara información de PDP en Excel/DOCX contra sus páginas web."""

    if not (excel_file.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Comparte un archivo Excel con extensión .xlsx.")
    if not (docx_file.filename or "").lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="Comparte un documento Word con extensión .docx.")

    settings = request.app.state.settings
    try:
        result = await PdpValidationService(settings).validate(
            await excel_file.read(),
            await docx_file.read(),
        )
    except (ValueError, RuntimeError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    ExecutionRepository(settings.database_path).create_execution(
        {
            "automation_type": "pdp_document_validation",
            "name": f"PDP vs DOCX ({result['summary']['programs']} programas)",
            "status": "SUCCESS" if result["status"] == "PASS" else "WARNING",
            "started_at": result["started_at"],
            "finished_at": result["finished_at"],
            "duration_seconds": result["duration_seconds"],
            "summary": (
                f"{result['summary']['programs']} PDP revisadas · "
                f"{result['summary']['failed']} secciones con diferencias."
            ),
            "error_message": None,
            "evidence_json": json.dumps(result, ensure_ascii=False),
            "created_at": result["finished_at"],
        }
    )
    return result


@router.post("/pdp/semantic-validate")
async def validate_pdp_semantic(
    request: Request,
    source_file: UploadFile = File(...),
    url: str = Form(...),
    use_ai: bool = Form(True),
) -> dict:
    """Compara cualquier documento admitido contra una única pÃ¡gina PDP."""

    settings = request.app.state.settings
    try:
        result = await GenericPdpValidationService(settings).validate(
            source_file.filename or "fuente",
            await source_file.read(),
            url.strip(),
            use_ai,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error

    summary = result["summary"]
    ExecutionRepository(settings.database_path).create_execution(
        {
            "automation_type": "pdp_semantic_validation",
            "name": f"PDP vs {result['source_filename']}",
            "status": "SUCCESS" if result["status"] == "PASS" else "WARNING",
            "started_at": result["started_at"],
            "finished_at": result["finished_at"],
            "duration_seconds": result["duration_seconds"],
            "summary": f"{summary['exact_matches'] + summary['normalized_matches']} coincidentes Â· {summary['missing']} faltantes Â· {summary['different']} diferentes.",
            "error_message": None,
            "evidence_json": json.dumps(result, ensure_ascii=False),
            "created_at": result["finished_at"],
        }
    )
    return result


@router.post("/bots/recorder/start", response_model=RecorderStartResponse)
async def start_bot_recorder(request: Request, config: RecorderStartRequest) -> dict:
    """Abre un navegador visible y comienza a capturar interacciones."""

    try:
        session = await request.app.state.recorder_manager.start(request.app.state.settings, config)
    except RuntimeError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"session_id": session.session_id, "status": "RECORDING", "url": config.url}


@router.get("/bots/recorder/{session_id}/events", response_model=RecorderEventsResponse)
async def recorder_events(request: Request, session_id: str) -> dict:
    """Entrega los eventos que el navegador ha capturado hasta este momento."""

    session = request.app.state.recorder_manager.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="La sesión de grabación no existe.")
    return {"events": session.get_events(), "active": session.active, "error": session.error}


@router.post("/bots/recorder/{session_id}/stop", response_model=RecorderStopResponse)
async def stop_bot_recorder(request: Request, session_id: str) -> dict:
    """Cierra la grabación y devuelve pasos listos para el constructor."""

    session = request.app.state.recorder_manager.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="La sesión de grabación no existe.")
    steps = await request.app.state.recorder_manager.stop(session_id)
    return {"status": "STOPPED", "url": session.config.url, "steps": steps}
