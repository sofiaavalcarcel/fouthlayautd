"""Punto de entrada de FastAPI para la plataforma de QA."""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .automations.generic_bot.recorder import RecorderManager
from .automations.utel_inconcert.runner import UtelInconcertRunner
from .api.routes import router
from .config.settings import Settings, get_settings
from .database.connection import initialize_database
from .services.logging_service import configure_logging, get_logger


FRONTEND_DIRECTORY = Path(__file__).resolve().parents[2] / "frontend"


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Prepara carpetas, base de datos y logs antes de atender solicitudes."""

    settings: Settings = application.state.settings
    settings.ensure_directories()
    configure_logging(settings.storage_dir, settings.log_level).info(
        "Backend iniciado en %s:%s", settings.api_host, settings.api_port
    )
    initialize_database(settings.database_path)
    try:
        yield
    finally:
        bot_tasks = list(application.state.bot_tasks.values())
        for task in bot_tasks:
            if not task.done():
                task.cancel()
        if bot_tasks:
            await asyncio.gather(*bot_tasks, return_exceptions=True)
        await UtelInconcertRunner._close_open_session()
        await application.state.recorder_manager.close_all()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Construye la aplicación para producción y para tests aislados."""

    application = FastAPI(
        title="QA Automation API",
        version="0.1.0",
        description="Backend para la aplicación web y desktop de automatizaciones de QA.",
        lifespan=lifespan,
    )
    # Electron carga desde file:// (origen "null"). La versión web se sirve
    # desde este mismo proceso y, por tanto, usa el mismo origen sin CORS.
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["null", "http://localhost:3000", "http://127.0.0.1:3000"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["*"],
    )

    @application.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, error: Exception) -> JSONResponse:
        """Registra el detalle técnico y entrega un mensaje apto para la interfaz."""

        get_logger().error(
            "Error no controlado en %s %s",
            request.method,
            request.url.path,
            exc_info=(type(error), error, error.__traceback__),
        )
        return JSONResponse(
            status_code=500,
            content={
                "detail": "No fue posible completar la operación. Revisa los logs del backend.",
                "error_code": "INTERNAL_ERROR",
            },
        )

    application.state.settings = settings or get_settings()
    application.state.recorder_manager = RecorderManager()
    application.state.bot_jobs = {}
    application.state.utel_inconcert_jobs = {}
    application.state.utel_batch_jobs = {}
    application.state.weekly_auto_jobs = {}
    application.state.bot_tasks = {}
    application.include_router(router)
    # Las capturas se guardan bajo storage y deben ser accesibles desde los
    # enlaces que devuelve Weekly Auto y los demás runners.
    application.state.settings.ensure_directories()
    screenshots_directory = application.state.settings.storage_dir / "screenshots"
    screenshots_directory.mkdir(parents=True, exist_ok=True)
    application.mount(
        "/screenshots",
        StaticFiles(directory=screenshots_directory),
        name="screenshots",
    )
    # Debe registrarse al final para que /api y /docs tengan prioridad.
    application.mount("/", StaticFiles(directory=FRONTEND_DIRECTORY, html=True), name="web-frontend")
    return application


app = create_app()
