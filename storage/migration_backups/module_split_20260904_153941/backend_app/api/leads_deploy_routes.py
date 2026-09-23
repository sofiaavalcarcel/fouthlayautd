"""Endpoints exclusivos de Bot Leads Deploy.

El namespace externo queda separado de Bot de nuevos productos. El motor batch
estable se reutiliza mediante un adaptador y recibe automation_module=leads_deploy.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from ..schemas.bot import BotStartResponse, UtelQaConfig, UtelQaJobResponse
from ..services.leads_deploy_spreadsheet_service import (
    LeadsDeploySpreadsheetService,
)
from .routes import (
    cancel_utel_batch,
    cancel_utel_run,
    download_utel_batch,
    run_utel_batch,
    run_utel_inconcert_bot,
    utel_batch_status,
    utel_inconcert_status,
)


router = APIRouter(prefix="/api/bots/leads-deploy", tags=["leads-deploy"])


@router.post("/spreadsheet-preview")
async def preview_leads_deploy_spreadsheet(
    file: UploadFile = File(...),
) -> dict:
    """Analiza únicamente el formato esperado por Leads Deploy."""

    if not (file.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(
            status_code=400,
            detail="Comparte un archivo Excel con extensión .xlsx.",
        )

    try:
        return LeadsDeploySpreadsheetService().preview(
            await file.read(),
            file.filename or "Leads Deploy.xlsx",
        )
    except Exception as error:
        raise HTTPException(
            status_code=400,
            detail=f"No fue posible analizar el Excel de Leads Deploy: {error}",
        ) from error


@router.post("/batch-run", status_code=202)
async def run_leads_deploy_batch(
    request: Request,
    file: UploadFile = File(...),
    config: str = Form(...),
    mapping: str = Form(...),
) -> dict:
    """Inicia el batch aislado marcándolo explícitamente como Leads Deploy."""

    try:
        raw_config = json.loads(config)
    except json.JSONDecodeError as error:
        raise HTTPException(
            status_code=400,
            detail="La configuración de Leads Deploy no es JSON válido.",
        ) from error

    raw_config["automation_module"] = "leads_deploy"
    raw_config["workflow_mode"] = "form_validation"

    return await run_utel_batch(
        request,
        file,
        json.dumps(raw_config, ensure_ascii=False),
        mapping,
    )


@router.get("/batch/{job_id}")
async def leads_deploy_batch_status(
    request: Request,
    job_id: str,
) -> dict:
    return await utel_batch_status(request, job_id)


@router.post("/batch/{job_id}/cancel")
async def cancel_leads_deploy_batch(
    request: Request,
    job_id: str,
) -> dict:
    return await cancel_utel_batch(request, job_id)


@router.get("/batch/{job_id}/download")
async def download_leads_deploy_batch(
    request: Request,
    job_id: str,
) -> FileResponse:
    return await download_utel_batch(request, job_id)


@router.post(
    "/run",
    response_model=BotStartResponse,
    status_code=202,
)
async def run_leads_deploy_single(
    request: Request,
    config: UtelQaConfig,
) -> dict:
    # El modo individual conserva por ahora el motor estable. El batch ya usa
    # LeadsDeployRunner y será el punto principal de evolución del módulo.
    return await run_utel_inconcert_bot(request, config)


@router.get(
    "/runs/{job_id}",
    response_model=UtelQaJobResponse,
)
async def leads_deploy_single_status(
    request: Request,
    job_id: str,
) -> dict:
    return await utel_inconcert_status(request, job_id)


@router.post("/runs/{job_id}/cancel")
async def cancel_leads_deploy_single(
    request: Request,
    job_id: str,
) -> dict:
    return await cancel_utel_run(request, job_id)
