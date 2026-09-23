from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from ..config.settings import Settings
from ..modules.strapi_products.description_runner import StrapiDescriptionRunner
from ..modules.strapi_products.fichas import FichasLookup
from ..modules.strapi_products.balancer_catalog import BalancerProgramCatalog
from ..modules.strapi_products.report import build_combined_report, build_description_report, build_report
from ..modules.strapi_products.country import COUNTRIES, detect_country_from_filename
from ..modules.strapi_products.schema_validation import product_schema_version
from ..modules.strapi_products.runner import StrapiProductRunner
from ..modules.strapi_products.spreadsheet import read_product_rows, select_product_rows
from ..services.strapi_client import StrapiClient
from ..services.google_drive_client import GoogleDriveClient


router = APIRouter(prefix="/api/strapi/products", tags=["strapi-products"])

DEFAULT_COUNTRIES = {
    item.label.casefold().replace(" ", "-"): {"label": item.label, "locale": item.locale, "slug": item.slug, "code": item.code}
    for item in COUNTRIES.values()
}


def _countries(settings: Settings) -> dict[str, dict[str, str]]:
    try:
        configured = json.loads(settings.strapi_countries_json)
        if isinstance(configured, dict) and configured:
            return configured
    except (TypeError, json.JSONDecodeError):
        pass
    return DEFAULT_COUNTRIES


def _token(settings: Settings) -> str:
    value = settings.strapi_token
    return value.get_secret_value() if hasattr(value, "get_secret_value") else str(value)


def _validate_product_scope(product_scope: str) -> str:
    if product_scope == "all":
        return product_scope
    if not product_scope.isdecimal() or len(product_scope) > 6 or not 1 <= int(product_scope) <= 100000:
        raise HTTPException(status_code=400, detail="product_scope debe ser un entero entre 1 y 100000 o all.")
    return product_scope


@router.get("/countries")
async def strapi_product_countries(request: Request) -> dict:
    return {"countries": _countries(request.app.state.settings)}


@router.post("/preview")
async def preview_strapi_product_file(file: UploadFile = File(...)) -> dict:
    if not (file.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Selecciona un archivo .xlsx.")
    try:
        rows = read_product_rows(await file.read())
        return {"filename": file.filename, "total": len(rows), "rows": [row.__dict__ for row in rows[:100]]}
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/run", status_code=202)
async def run_strapi_product_job(request: Request, file: UploadFile = File(...), country: str = Form(""), product_scope: str = Form("2"), dry_run: str = Form("true")) -> dict:
    settings: Settings = request.app.state.settings
    if not (file.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Selecciona un archivo .xlsx.")
    if dry_run.casefold() not in {"true", "false"}:
        raise HTTPException(status_code=400, detail="dry_run debe ser true o false.")
    _validate_product_scope(product_scope)
    try:
        detected = detect_country_from_filename(file.filename or "")
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    country_config = {"label": detected.label, "locale": detected.locale, "slug": detected.slug, "code": detected.code}
    if not settings.strapi_url or not _token(settings):
        raise HTTPException(status_code=500, detail="Faltan STRAPI_URL o STRAPI_TOKEN en la configuracion del backend.")

    content = await file.read()
    job_id = uuid4().hex
    request.app.state.strapi_product_jobs[job_id] = {
        "job_id": job_id, "status": "RUNNING", "country": detected.label, "country_code": detected.code, "locale": detected.locale, "dry_run": dry_run.casefold() == "true",
        "filename": file.filename, "product_scope": product_scope, "started_at": datetime.now(timezone.utc).isoformat(), "completed": 0,
    }
    request.app.state.bot_tasks[job_id] = asyncio.create_task(_run_job(request.app, job_id, content, file.filename or "resultado.xlsx", country_config, product_scope))
    return request.app.state.strapi_product_jobs[job_id]


@router.post("/descriptions/run", status_code=202)
async def run_strapi_description_job(request: Request, file: UploadFile = File(...), fichas_file: UploadFile | None = File(None), product_scope: str = Form("2"), dry_run: str = Form("true")) -> dict:
    settings: Settings = request.app.state.settings
    if not (file.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Selecciona un archivo .xlsx.")
    if fichas_file and not (fichas_file.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="El archivo de fichas debe ser .xlsx.")
    _validate_product_scope(product_scope)
    if dry_run.casefold() not in {"true", "false"}:
        raise HTTPException(status_code=400, detail="dry_run debe ser true o false.")
    try:
        detected = detect_country_from_filename(file.filename or "")
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    if not settings.strapi_url or not _token(settings):
        raise HTTPException(status_code=500, detail="Faltan STRAPI_URL o STRAPI_TOKEN en la configuracion del backend.")

    job_id = uuid4().hex
    content = await file.read()
    fichas_content = await fichas_file.read() if fichas_file else None
    request.app.state.strapi_product_jobs[job_id] = {
        "job_id": job_id, "operation": "descriptions", "status": "RUNNING", "country": detected.label, "country_code": detected.code, "locale": detected.locale,
        "dry_run": dry_run.casefold() == "true", "filename": file.filename, "product_scope": product_scope, "schema_version": product_schema_version(), "schema_source": "integrado", "started_at": datetime.now(timezone.utc).isoformat(), "completed": 0,
    }
    request.app.state.bot_tasks[job_id] = asyncio.create_task(_run_description_job(request.app, job_id, content, file.filename or "resultado.xlsx", detected, fichas_content, product_scope))
    return request.app.state.strapi_product_jobs[job_id]


@router.get("/jobs/{job_id}")
async def strapi_product_job_status(request: Request, job_id: str) -> dict:
    job = request.app.state.strapi_product_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado.")
    return job


@router.get("/jobs/{job_id}/download")
async def download_strapi_product_report(request: Request, job_id: str) -> FileResponse:
    job = request.app.state.strapi_product_jobs.get(job_id)
    if not job or not job.get("report_path"):
        raise HTTPException(status_code=404, detail="El reporte aun no esta disponible.")
    return FileResponse(job["report_path"], filename=Path(job["report_path"]).name, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@router.post("/combined-report", status_code=201)
async def create_combined_strapi_product_report(request: Request, canonical_job_id: str = Form(...), pdp_job_id: str = Form(...)) -> dict:
    jobs = request.app.state.strapi_product_jobs
    canonical_job = jobs.get(canonical_job_id)
    pdp_job = jobs.get(pdp_job_id)
    if not canonical_job or not pdp_job:
        raise HTTPException(status_code=404, detail="No se encontraron los dos procesos para crear el reporte.")
    if canonical_job.get("status") not in {"SUCCESS", "WARNING"} or pdp_job.get("status") not in {"SUCCESS", "WARNING"}:
        raise HTTPException(status_code=409, detail="Ambos procesos deben terminar correctamente antes de crear el reporte.")
    if any(canonical_job.get(key) != pdp_job.get(key) for key in ("filename", "product_scope", "dry_run", "country_code")):
        raise HTTPException(status_code=400, detail="Los procesos no corresponden al mismo archivo, país, alcance y modo de ejecución.")

    report_id = uuid4().hex
    report_dir = request.app.state.settings.storage_dir / "reports" / "strapi"
    report_dir.mkdir(parents=True, exist_ok=True)
    filename = Path(pdp_job.get("filename") or "productos.xlsx").stem
    report_path = report_dir / f"{report_id}_{filename}_proceso_completo.xlsx"
    report_path.write_bytes(build_combined_report(canonical_job, pdp_job))
    jobs[report_id] = {
        "job_id": report_id,
        "status": "SUCCESS",
        "report_path": str(report_path),
        "download_url": f"/api/strapi/products/jobs/{report_id}/download",
    }
    return {"job_id": report_id, "download_url": jobs[report_id]["download_url"]}


async def _run_job(application, job_id: str, content: bytes, filename: str, country_config: dict[str, str], product_scope: str = "2") -> None:
    settings: Settings = application.state.settings
    job = application.state.strapi_product_jobs[job_id]
    client = None
    try:
        all_rows = read_product_rows(content)
        rows = select_product_rows(all_rows, product_scope)
        job.update({"input_total": len(all_rows), "selected_total": len(rows)})
        slug_map = {key: value["slug"] for key, value in _countries(settings).items() if value.get("slug")}
        slug_map.update({item.label.casefold(): item.slug for item in COUNTRIES.values()})
        client = StrapiClient(settings.strapi_url, _token(settings), settings.strapi_product_endpoint, settings.strapi_timeout_seconds)
        runner = StrapiProductRunner(client, country_config["label"], country_config["locale"], slug_map, dry_run=job["dry_run"], expected_host=settings.strapi_expected_host, title_field=settings.strapi_program_field, seo_field=settings.strapi_seo_field, canonical_field=settings.strapi_canonical_field, status=settings.strapi_content_status, progress_callback=lambda message: job.update({"progress_message": message}))
        results, summary = await runner.run(rows)
        report_dir = settings.storage_dir / "reports" / "strapi"
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / f"{job_id}_{Path(filename).stem}.xlsx"
        report_path.write_bytes(build_report(results, summary))
        job.update({"status": "SUCCESS" if not summary.failed and not summary.invalid_data else "WARNING", "completed": summary.total, "summary": summary.as_dict(), "results": [result.as_dict() for result in results], "report_path": str(report_path), "download_url": f"/api/strapi/products/jobs/{job_id}/download", "finished_at": datetime.now(timezone.utc).isoformat()})
    except Exception as error:  # noqa: BLE001
        job.update({"status": "FAILED", "message": str(error), "finished_at": datetime.now(timezone.utc).isoformat()})
    finally:
        if client:
            await client.close()


async def _run_description_job(application, job_id: str, content: bytes, filename: str, country_config, fichas_content: bytes | None = None, product_scope: str = "2") -> None:
    settings: Settings = application.state.settings
    job = application.state.strapi_product_jobs[job_id]
    client = None
    drive_client = None
    balancer_catalog = None
    try:
        all_rows = read_product_rows(content)
        rows = select_product_rows(all_rows, product_scope)
        job.update({"input_total": len(all_rows), "selected_total": len(rows)})
        client = StrapiClient(settings.strapi_url, _token(settings), settings.strapi_product_endpoint, settings.strapi_timeout_seconds)
        drive_client = GoogleDriveClient(
            settings.google_drive_client_id.get_secret_value(),
            settings.google_drive_client_secret.get_secret_value(),
            settings.google_drive_refresh_token.get_secret_value(),
        )
        fichas_path = settings.fichas_path
        if fichas_content is not None:
            fichas = FichasLookup(fichas_content)
        else:
            if not fichas_path.is_file():
                downloads_path = Path.home() / "Downloads" / "fichas.xlsx"
                fichas_path = downloads_path if downloads_path.is_file() else fichas_path
            fichas = FichasLookup(fichas_path) if fichas_path.is_file() else None
        username = settings.lead_balancer_username
        password = settings.lead_balancer_password
        username = username.get_secret_value() if hasattr(username, "get_secret_value") else str(username)
        password = password.get_secret_value() if hasattr(password, "get_secret_value") else str(password)
        siu_key_lookup = None
        if not username or not password:
            raise ValueError("Faltan las credenciales del Balanceador; se cancela PDP para no guardar el producto sin siuKey/bannerKey.")
        balancer_catalog = BalancerProgramCatalog(
            settings.lead_balancer_url,
            username,
            password,
            progress_callback=lambda message: job.update({"progress_message": message}),
        )
        siu_key_lookup = balancer_catalog.get_siu_key
        runner = StrapiDescriptionRunner(client, country_config.label, country_config.locale, dry_run=job["dry_run"], short_field=settings.strapi_short_description_field, long_field=settings.strapi_long_description_field, content_field=settings.strapi_content_description_field, programs_field=settings.strapi_programs_field, download_program_field=settings.strapi_download_program_field, experience_field=settings.strapi_experience_field, subjects_field=settings.strapi_subjects_field, siu_key_field=settings.strapi_siu_key_field, banner_key_field=settings.strapi_banner_key_field, siu_key_lookup=siu_key_lookup, fichas_lookup=fichas, title_field=settings.strapi_program_field, status=settings.strapi_content_status, google_drive_client=drive_client, progress_callback=lambda message: job.update({"progress_message": message}), stg_environment=settings.strapi_environment.casefold() == "stg")
        results, summary = await runner.run(rows)
        balancer_blockers = [
            result.message for result in results
            if result.status == "FAILED" and result.message and "balanceador" in result.message.casefold()
        ]
        report_dir = settings.storage_dir / "reports" / "strapi"
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / f"{job_id}_{Path(filename).stem}_descriptions.xlsx"
        report_path.write_bytes(build_description_report(results, summary))
        job.update({"status": "SUCCESS" if not summary.failed and not summary.invalid_data else "WARNING", "completed": summary.total, "summary": summary.as_dict(), "results": [result.as_dict() for result in results], "blocking_reason": balancer_blockers[0] if balancer_blockers else None, "report_path": str(report_path), "download_url": f"/api/strapi/products/jobs/{job_id}/download", "finished_at": datetime.now(timezone.utc).isoformat()})
    except Exception as error:  # noqa: BLE001
        job.update({"status": "FAILED", "message": str(error), "finished_at": datetime.now(timezone.utc).isoformat()})
    finally:
        if client:
            await client.close()
        if drive_client:
            await drive_client.close()
        if balancer_catalog:
            await balancer_catalog.close()
