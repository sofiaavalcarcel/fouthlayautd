"""API no bloqueante del procesamiento PageSpeed de Weekly Performance."""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import ValidationError

from ..database.repository import ExecutionRepository
from ..modules.weekly_auto.weekly_performance import (
    WeeklyPerformanceCancelled,
    WeeklyPerformanceConfig,
    WeeklyPerformanceError,
    WeeklyPerformanceRunner,
)
from ..services.logging_service import get_logger


router = APIRouter(prefix="/api/weekly-auto/performance", tags=["weekly-performance"])
logger = get_logger()
XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _public_job(job: dict[str, Any]) -> dict[str, Any]:
    """Evita exponer rutas locales y datos internos del worker."""

    return {key: value for key, value in job.items() if not key.startswith("_")}


def _safe_stem(filename: str) -> str:
    stem = Path(filename or "weekly-performance").stem
    cleaned = re.sub(r"[^\w.-]+", "-", stem, flags=re.UNICODE).strip("-._")
    return cleaned[:80] or "weekly-performance"


def _record_execution(app: Any, job: dict[str, Any], *, error: str | None = None) -> None:
    status = job.get("status")
    repository_status = "SUCCESS" if status == "PASS" else "WARNING" if status == "CANCELLED" else "FAIL"
    evidence = {
        "job_id": job["job_id"],
        "total": job.get("total", 0),
        "completed": job.get("completed", 0),
        "successful": job.get("successful", 0),
        "failed": job.get("failed", 0),
        "download_url": job.get("download_url"),
    }
    ExecutionRepository(app.state.settings.database_path).create_execution(
        {
            "automation_type": "weekly_performance",
            "name": job.get("name", "Weekly Performance"),
            "status": repository_status,
            "started_at": job["started_at"],
            "finished_at": job.get("finished_at"),
            "duration_seconds": job.get("duration_seconds"),
            "summary": job.get("summary"),
            "error_message": error,
            "evidence_json": json.dumps(evidence, ensure_ascii=False),
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
    )


async def _run_job(app: Any, job_id: str, content: bytes, config: WeeklyPerformanceConfig) -> None:
    job = app.state.weekly_performance_jobs[job_id]
    runner = WeeklyPerformanceRunner(app.state.settings)
    started = perf_counter()
    output_path = Path(job["_output_path"])

    def should_stop() -> bool:
        return bool(job.get("cancel_requested"))

    def update_progress(progress: dict[str, Any]) -> None:
        job.update(
            {
                "completed": progress["completed"],
                "current_row": progress["row"],
                "current_url": progress["url"],
                "current_desktop": progress["desktop"],
                "current_mobile": progress["mobile"],
            }
        )
        if progress["status"] == "PASS":
            job["successful"] += 1
        else:
            job["failed"] += 1
        job["summary"] = (
            f"Fila {progress['row']} procesada: Desktop {progress['desktop']} · "
            f"Móvil {progress['mobile']}."
        )

    try:
        job["status"] = "RUNNING"
        result = await runner.run(
            content,
            output_path,
            config,
            should_stop=should_stop,
            progress_callback=update_progress,
        )
        job.update(
            {
                "status": result["status"],
                "completed": result["completed"],
                "successful": result["successful"],
                "failed": result["failed"],
                "summary": result["summary"],
                "results": result["results"],
                "download_url": f"/api/weekly-auto/performance/runs/{job_id}/download",
            }
        )
    except WeeklyPerformanceCancelled as error:
        job.update(
            {
                "status": "CANCELLED",
                "summary": f"Ejecución detenida. Se conservaron {job['completed']} resultados.",
                "last_error": str(error),
                "download_url": (
                    f"/api/weekly-auto/performance/runs/{job_id}/download"
                    if output_path.is_file()
                    else None
                ),
            }
        )
    except asyncio.CancelledError:
        job.update(
            {
                "status": "CANCELLED",
                "summary": f"Ejecución interrumpida. Se conservaron {job['completed']} resultados.",
                "download_url": (
                    f"/api/weekly-auto/performance/runs/{job_id}/download"
                    if output_path.is_file()
                    else None
                ),
            }
        )
    except Exception as error:  # noqa: BLE001 - el trabajo debe quedar consultable
        logger.exception("Weekly Performance falló en el trabajo %s", job_id)
        job.update(
            {
                "status": "FAIL",
                "summary": "Weekly Performance no pudo completar el Excel.",
                "last_error": str(error),
                "download_url": (
                    f"/api/weekly-auto/performance/runs/{job_id}/download"
                    if output_path.is_file()
                    else None
                ),
            }
        )
    finally:
        job["finished_at"] = datetime.now().isoformat(timespec="seconds")
        job["duration_seconds"] = round(perf_counter() - started, 2)
        try:
            _record_execution(app, job, error=job.get("last_error"))
        except Exception:  # noqa: BLE001 - el historial no debe ocultar el resultado
            logger.exception("No se pudo registrar Weekly Performance %s en el historial", job_id)


@router.post("/run", status_code=202)
async def run_weekly_performance(
    request: Request,
    file: UploadFile = File(...),
    sheet_name: str = Form("Hoja 1"),
    max_workers: int = Form(8),
) -> dict[str, Any]:
    """Valida el Excel e inicia las mediciones sin bloquear la API."""

    filename = file.filename or "weekly-performance.xlsx"
    if not filename.casefold().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Comparte un archivo Excel con extensión .xlsx.")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="El archivo Excel está vacío.")
    try:
        config = WeeklyPerformanceConfig(sheet_name=sheet_name, max_workers=max_workers)
        inspected = WeeklyPerformanceRunner(request.app.state.settings).inspect(content, config.sheet_name)
    except (ValidationError, WeeklyPerformanceError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    job_id = uuid4().hex
    output_directory = request.app.state.settings.storage_dir / "reports" / "weekly_performance"
    output_directory.mkdir(parents=True, exist_ok=True)
    output_path = output_directory / f"{job_id}_{_safe_stem(filename)}_resultados.xlsx"
    job = {
        "job_id": job_id,
        "name": "Weekly Performance",
        "status": "QUEUED",
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "finished_at": None,
        "duration_seconds": None,
        "sheet_name": config.sheet_name,
        "max_workers": config.max_workers,
        "total": inspected["total_urls"],
        "completed": 0,
        "successful": 0,
        "failed": 0,
        "current_row": None,
        "current_url": None,
        "current_desktop": None,
        "current_mobile": None,
        "summary": f"{inspected['total_urls']} URLs listas para procesar.",
        "last_error": None,
        "download_url": None,
        "cancel_requested": False,
        "results": [],
        "_output_path": str(output_path),
        "_download_filename": f"{_safe_stem(filename)}_resultados.xlsx",
    }
    request.app.state.weekly_performance_jobs[job_id] = job
    task_key = f"weekly-performance:{job_id}"
    task = asyncio.create_task(_run_job(request.app, job_id, content, config))
    request.app.state.bot_tasks[task_key] = task
    task.add_done_callback(lambda _: request.app.state.bot_tasks.pop(task_key, None))
    return _public_job(job)


@router.get("/runs/{job_id}")
async def weekly_performance_status(request: Request, job_id: str) -> dict[str, Any]:
    job = request.app.state.weekly_performance_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="La ejecución no existe o ya no está disponible.")
    return _public_job(job)


@router.post("/runs/{job_id}/cancel")
async def cancel_weekly_performance(request: Request, job_id: str) -> dict[str, Any]:
    job = request.app.state.weekly_performance_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="La ejecución no existe o ya no está disponible.")
    if job["status"] not in {"QUEUED", "RUNNING"}:
        raise HTTPException(status_code=409, detail="La ejecución ya terminó.")
    job["cancel_requested"] = True
    job["summary"] = "Deteniendo solicitudes PageSpeed y guardando el Excel parcial."
    return _public_job(job)


@router.get("/runs/{job_id}/download")
async def download_weekly_performance(request: Request, job_id: str) -> FileResponse:
    job = request.app.state.weekly_performance_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="La ejecución no existe o ya no está disponible.")
    output_path = Path(job["_output_path"])
    if not output_path.is_file():
        raise HTTPException(status_code=404, detail="El Excel todavía no está disponible.")
    return FileResponse(output_path, filename=job["_download_filename"], media_type=XLSX_MEDIA_TYPE)
