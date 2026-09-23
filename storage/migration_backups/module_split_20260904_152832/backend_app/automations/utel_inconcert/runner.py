"""Flujo QA real para enviar un lead UTEL y verificarlo en InConcert."""

import asyncio
import re
import secrets
import unicodedata
from contextlib import asynccontextmanager, suppress
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from time import perf_counter
from typing import Any, Awaitable, Callable
from urllib.parse import urljoin, urlparse

from pydantic import SecretStr

from ...config.settings import Settings
from ...schemas.bot import UtelQaConfig, UtelQaStageResult
from ...services.logging_service import get_logger
from ...services.doctorate_link_catalog import DoctorateLinkCatalog
from ...services.program_rotation_service import ProgramRotationService


class UtelQaError(RuntimeError):
    """Error de negocio con contexto suficiente para el reporte QA."""

    def __init__(self, stage: str, message: str, selector: str | None = None):
        super().__init__(message)
        self.stage = stage
        self.selector = selector
        self.screenshot: str | None = None
        self.url: str | None = None


class PostSubmitSignal(UtelQaError):
    """Señal posterior al clic: consultar CRM y nunca volver a enviar."""


class UnconfirmedSubmission(PostSubmitSignal):
    """UTEL no mostró una respuesta concluyente después del clic."""


class RejectedSubmission(PostSubmitSignal):
    """UTEL mostró un rechazo genérico después del clic, aún sujeto a CRM."""


class LeadNotFoundError(UtelQaError):
    """La ventana completa de búsqueda terminó sin encontrar el lead."""


class UtelRunCancelled(RuntimeError):
    """Detención solicitada por el usuario durante una ejecución."""


class UtelInconcertRunner:
    """Ejecuta el flujo UTEL -> InConcert usando Playwright."""

    FORM_IDS = {"lateral": "LateralBLC", "tarjeta": "TarjetaBLC", "footer": "FooterBLC"}
    FORM_WAIT_TIMEOUT_MS = 30000
    FORM_RECHECK_TIMEOUT_MS = 15000
    FORM_POLL_INTERVAL_SECONDS = 0.5
    COUNTRY_CODES = {
        "mexico": "+52",
        "mÃ©xico": "+52",
        "ecuador": "+593",
        "colombia": "+57",
        "peru": "+51",
        "perÃº": "+51",
        "chile": "+56",
        "argentina": "+54",
        "usa": "+1",
        "united states": "+1",
        "estados unidos": "+1",
        "bolivia": "+591",
        "paraguay": "+595",
        "dominicana": "+1",
        "republica dominicana": "+1",
        "dominican republic": "+1",
        "guatemala": "+502",
        "panama": "+507",
        "el salvador": "+503",
        "global": "+1",
        "filipinas": "+63",
        "philippines": "+63",
        "india": "+91",
    }
    # Los valores reales del <select> están en inglés y no son los prefijos
    # telefónicos que muestra visualmente el componente. Estos alias permiten
    # seleccionar el país correcto y comprobarlo antes de escribir el teléfono.
    COUNTRY_OPTION_ALIASES = {
        "mexico": ("mexico",),
        "peru": ("peru",),
        "usa": ("united states",),
        "united states": ("united states",),
        "estados unidos": ("united states",),
        "dominicana": ("dominican republic", "republica dominicana"),
        "republica dominicana": ("dominican republic", "republica dominicana"),
        "dominican republic": ("dominican republic", "republica dominicana"),
        "global": ("united states",),
        "filipinas": ("philippines",),
        "philippines": ("philippines",),
    }
    _open_session: dict[str, Any] | None = None

    def __init__(self, settings: Settings):
        self.settings = settings
        self.logger = get_logger()
        self.stage_results: list[UtelQaStageResult] = []
        self.screenshots: list[str] = []
        self.evidence_directory: Path | None = None
        self.lead_url: str | None = None
        self.selected_program_name = ""
        self._selected_direct_url = ""
        self._selected_direct_page_program = ""
        self._rotation_config = None
        self._crm_session_recoveries = 0
        self._crm_origin = ""
        self._submission_attempted = False
        self._cancelled_before_submit = False
        self._cancelled = False
        self.program_selection_notice = ""
        self.status_flags = {
            "utel_submission": "pending",
            "utel_submission_message": "Formulario pendiente de envio.",
            "inconcert_login": "pending",
            "lead_found": "pending",
            "lead_source": "pending",
            "conversion_found": "pending",
        }
        self._last_submit_success_pattern = ""
        self._last_submit_error_pattern = "error|invalido|inválido|obligatorio|requerido|fall"

    async def run(
        self,
        config: UtelQaConfig,
        should_stop: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        """Valida configuracion, ejecuta el flujo y devuelve un reporte estructurado."""

        started_at = datetime.now().isoformat(timespec="seconds")
        timer = perf_counter()
        self.stage_results = []
        self.screenshots = []
        self.lead_url = None
        self.selected_program_name = ""
        self._selected_direct_url = ""
        self._selected_direct_page_program = ""
        self._rotation_config = config
        self._crm_session_recoveries = 0
        self._crm_origin = ""
        self._submission_attempted = False
        self._cancelled_before_submit = False
        self._cancelled = False
        self.program_selection_notice = ""
        self.status_flags = {key: "pending" for key in self.status_flags}
        self.evidence_directory = self._evidence_directory(config.name)
        page = None
        post_submit_signal: PostSubmitSignal | None = None

        try:
            self._validate_config(config)
            self._raise_if_stop_requested(should_stop)
            try:
                from playwright.async_api import TimeoutError as PlaywrightTimeoutError
                from playwright.async_api import async_playwright
            except ImportError as error:
                raise RuntimeError(
                    "Playwright no esta instalado. Ejecuta `python -m pip install -r backend/requirements.txt` "
                    "y despues `python -m playwright install chromium`."
                ) from error

            await self._close_open_session()
            keep_open = {"value": config.keep_browser_open}
            async with self._playwright(async_playwright, keep_open) as playwright:
                browser = None
                context = None
                launch_headless = False if config.keep_browser_open else config.headless
                if config.browser == "chrome":
                    profile_directory = self.settings.storage_dir / "browser_profiles" / "chrome-qa"
                    profile_directory.mkdir(parents=True, exist_ok=True)
                    context = await playwright.chromium.launch_persistent_context(
                        str(profile_directory),
                        channel="chrome",
                        headless=launch_headless,
                        viewport={"width": 1440, "height": 900},
                    )
                else:
                    browser_type = getattr(playwright, config.browser)
                    browser = await browser_type.launch(headless=launch_headless)
                    context = await browser.new_context(viewport={"width": 1440, "height": 900})
                try:
                    if config.verification_only:
                        self.status_flags["utel_submission"] = "skipped"
                        self.status_flags["utel_submission_message"] = "Envio ya realizado en la fase UTEL."
                        if self._lead_origin_is_balanceador(config):
                            balancer_page = await context.new_page()
                            page = balancer_page
                            balancer_page.set_default_timeout(30000)
                            await self._run_stage(
                                1,
                                "lead_balancer_search",
                                "Lead localizado en Balanceador",
                                balancer_page,
                                lambda: self._search_lead_balancer(
                                    balancer_page, config.lead.email, config.lead.name
                                ),
                            )
                            self.status_flags["lead_source"] = "balanceador"
                            self.status_flags["lead_found"] = "success"
                            self.status_flags["conversion_found"] = "skipped"
                            return self._build_result(config, started_at, timer)
                        inconcert_page = await context.new_page()
                        page = inconcert_page
                        inconcert_page.set_default_timeout(30000)
                        await self._run_stage(1, "inconcert_open", "InConcert disponible para verificacion", inconcert_page, lambda: self._open_inconcert(inconcert_page, config))
                        await self._run_stage(2, "inconcert_login", "Login de InConcert completado", inconcert_page, lambda: self._login_inconcert(inconcert_page))
                        self.status_flags["inconcert_login"] = "success"
                        await self._run_stage(3, "inconcert_contacts", "Contactos listos para buscar", inconcert_page, lambda: self._open_contacts(inconcert_page))
                        try:
                            await self._run_stage(4, "inconcert_search", "Lead localizado y verificado", inconcert_page, lambda: self._search_lead(inconcert_page, config.lead.email, config.lead.name))
                            self.status_flags["lead_source"] = "inconcert"
                            self.status_flags["lead_found"] = "success"
                            inconcert_page = await self._run_stage(
                                5,
                                "inconcert_manage",
                                "Gestionar abierto, actividad cargada y email confirmado",
                                inconcert_page,
                                lambda: self._open_manage(
                                    inconcert_page,
                                    config.lead.name,
                                    config.lead.email,
                                ),
                            )
                            page = inconcert_page
                        except UtelQaError as search_error:
                            if search_error.stage != "inconcert_search":
                                raise
                            balancer_page = await context.new_page()
                            page = balancer_page
                            balancer_page.set_default_timeout(30000)
                            try:
                                await self._run_stage(5, "lead_balancer_search", "Lead localizado en Balanceador", balancer_page, lambda: self._search_lead_balancer(balancer_page, config.lead.email, config.lead.name))
                            except LeadNotFoundError:
                                # InConcert y el Balanceador agotaron sus ventanas
                                # de indexación: esta ausencia sí es concluyente.
                                self.status_flags["lead_found"] = "failed"
                                raise
                            self.status_flags["lead_source"] = "balanceador"
                            self.status_flags["lead_found"] = "success"
                            self.status_flags["conversion_found"] = "skipped"
                            return self._build_result(config, started_at, timer)
                        if config.workflow_mode == "form_validation":
                            self.status_flags["conversion_found"] = "skipped"
                            return self._build_result(config, started_at, timer)
                        await self._run_stage(6, "inconcert_conversion", "Conversion encontrada y programa validado", inconcert_page, lambda: self._confirm_conversion(inconcert_page, config))
                        self.status_flags["conversion_found"] = "success"
                        return self._build_result(config, started_at, timer)
                    utel_page = await context.new_page()
                    page = utel_page
                    utel_page.set_default_timeout(18000)
                    await self._run_stage(1, "utel_open", "UTEL abierta", utel_page, lambda: self._open_utel(utel_page, config), "01_utel_inicio")
                    self._raise_if_stop_requested(should_stop)
                    await self._run_stage(2, "utel_navigation", "Modalidad, nivel y programa resueltos", utel_page, lambda: self._navigate_utel(utel_page, config))
                    self._raise_if_stop_requested(should_stop)
                    form = await self._run_stage(3, "utel_form", "Formulario identificado", utel_page, lambda: self._find_utel_form(utel_page, config))
                    await self._run_stage(4, "utel_fill", "Formulario rellenado", utel_page, lambda: self._fill_utel_form(utel_page, form, config), "02_formulario_lleno")
                    self._raise_if_stop_requested(should_stop)
                    if config.dry_run:
                        await self._run_stage(5, "dry_run_stop", "Dry run: formulario listo, envio omitido", utel_page, lambda: self._dry_run_stop(), "03_dry_run_pre_envio")
                        self.status_flags = {key: "skipped" for key in self.status_flags}
                        return self._build_result(config, started_at, timer)
                    # La fila se envía en UTEL antes de abrir o consultar el CRM.
                    # El preflight del lote es una comprobación separada: no busca correos.
                    page = utel_page
                    await self._show_active_page(utel_page)
                    self._raise_if_stop_requested(should_stop)

                    post_submit_signal = None
                    verification_destination = (
                        "Balanceador"
                        if self._lead_origin_is_balanceador(config)
                        else "InConcert"
                    )
                    submit_success_message = (
                        "Formulario enviado; verificación pendiente al final del lote"
                        if config.defer_crm_verification
                        else f"Formulario enviado; se verificará en {verification_destination}"
                    )
                    try:
                        await self._run_stage(
                            5,
                            "utel_submit",
                            submit_success_message,
                            utel_page,
                            lambda: self._submit_utel_form(utel_page, form, should_stop),
                            "03_formulario_enviado",
                        )
                    except PostSubmitSignal as error:
                        # _submit_utel_form solo emite esta señal después de observar
                        # el POST real. Por seguridad se consulta CRM sin reenviar.
                        post_submit_signal = error
                        self.logger.warning(
                            "%s Se verificará en CRM sin reenviar el formulario.",
                            error,
                        )

                    # Defensa adicional: ninguna búsqueda puede comenzar sin haber
                    # observado primero la solicitud POST /api/forms de UTEL.
                    if not self._submission_attempted:
                        raise UtelQaError(
                            "utel_submit",
                            "UTEL no generó POST /api/forms. El formulario no se considera "
                            "enviado y no se consultará InConcert ni Balanceador.",
                            'button[type="submit"], input[type="submit"]',
                        )

                    self.status_flags["utel_submission"] = (
                        "pending" if post_submit_signal else "success"
                    )
                    self.status_flags["utel_submission_message"] = (
                        str(post_submit_signal)
                        if post_submit_signal
                        else "Formulario enviado y confirmado correctamente."
                    )

                    if config.defer_crm_verification:
                        self.status_flags["inconcert_login"] = "skipped"
                        self.status_flags["lead_found"] = "pending"
                        self.status_flags["conversion_found"] = "pending"
                        return self._build_result(config, started_at, timer)

                    if self._lead_origin_is_balanceador(config):
                        balancer_page = await context.new_page()
                        page = balancer_page
                        balancer_page.set_default_timeout(30000)
                        await self._show_active_page(balancer_page)
                        await self._run_stage(
                            6,
                            "lead_balancer_search",
                            "Lead localizado en Balanceador",
                            balancer_page,
                            lambda: self._search_lead_balancer(
                                balancer_page, config.lead.email, config.lead.name
                            ),
                            "05_lead_balanceador",
                        )
                        self.status_flags["lead_source"] = "balanceador"
                        self.status_flags["lead_found"] = "success"
                        self.status_flags["conversion_found"] = "skipped"
                        self._mark_submission_verified(post_submit_signal)
                        return self._build_result(config, started_at, timer)

                    # Solo después de confirmar el POST de UTEL se abre InConcert.
                    inconcert_page = await context.new_page()
                    page = inconcert_page
                    inconcert_page.set_default_timeout(30000)
                    await self._run_stage(
                        6,
                        "inconcert_open",
                        "InConcert disponible después del envío",
                        inconcert_page,
                        lambda: self._open_inconcert(inconcert_page, config),
                    )
                    await self._run_stage(
                        7,
                        "inconcert_login",
                        "Login de InConcert completado",
                        inconcert_page,
                        lambda: self._login_inconcert(inconcert_page),
                        "04_inconcert_login",
                    )
                    self.status_flags["inconcert_login"] = "success"
                    await self._run_stage(
                        8,
                        "inconcert_contacts",
                        "Contactos listos para buscar el lead enviado",
                        inconcert_page,
                        lambda: self._open_contacts(inconcert_page),
                    )

                    page = inconcert_page
                    await self._show_active_page(inconcert_page)
                    try:
                        await self._run_stage(
                            9,
                            "inconcert_search",
                            "Lead localizado y verificado",
                            inconcert_page,
                            lambda: self._search_lead(
                                inconcert_page,
                                config.lead.email,
                                config.lead.name,
                            ),
                            "05_lead_encontrado",
                        )
                        self.status_flags["lead_source"] = "inconcert"
                    except UtelQaError as search_error:
                        if search_error.stage != "inconcert_search":
                            raise
                        self.logger.warning(
                            "El lead %s no apareció en InConcert; se consultará el "
                            "Balanceador como respaldo.",
                            config.lead.email,
                        )
                        balancer_page = await context.new_page()
                        balancer_page.set_default_timeout(30000)
                        page = balancer_page
                        await self._show_active_page(balancer_page)
                        try:
                            await self._run_stage(
                                10,
                                "lead_balancer_search",
                                "Lead localizado en Balanceador",
                                balancer_page,
                                lambda: self._search_lead_balancer(
                                    balancer_page,
                                    config.lead.email,
                                    config.lead.name,
                                ),
                                "05_lead_balanceador",
                            )
                        except LeadNotFoundError:
                            self.status_flags["lead_found"] = "failed"
                            raise
                        self.status_flags["lead_source"] = "balanceador"
                        self.status_flags["lead_found"] = "success"
                        self.status_flags["conversion_found"] = "skipped"
                        self._mark_submission_verified(post_submit_signal)
                        return self._build_result(config, started_at, timer)

                    self.status_flags["lead_found"] = "success"
                    inconcert_page = await self._run_stage(
                        10,
                        "inconcert_manage",
                        "Gestionar abierto, actividad cargada y email confirmado",
                        inconcert_page,
                        lambda: self._open_manage(
                            inconcert_page,
                            config.lead.name,
                            config.lead.email,
                        ),
                        "06_gestionar",
                    )
                    page = inconcert_page
                    self._mark_submission_verified(post_submit_signal)
                    if config.workflow_mode == "form_validation":
                        self.status_flags["conversion_found"] = "skipped"
                        return self._build_result(config, started_at, timer)
                    await self._run_stage(
                        11,
                        "inconcert_conversion",
                        "Conversion encontrada y programa validado",
                        inconcert_page,
                        lambda: self._confirm_conversion(inconcert_page, config),
                        "07_conversion",
                    )
                    self.status_flags["conversion_found"] = "success"
                finally:
                    current_task = asyncio.current_task()
                    task_is_cancelling = bool(
                        current_task is not None and current_task.cancelling()
                    )
                    if (
                        config.keep_browser_open
                        and not self._cancelled_before_submit
                        and not self._cancelled
                        and not task_is_cancelling
                    ):
                        keep_open["value"] = True
                        UtelInconcertRunner._open_session = {
                            "playwright": playwright,
                            "context": context,
                            "browser": browser,
                        }
                        self.logger.info("El navegador quedo abierto para revision manual.")
                    else:
                        await context.close()
                        if browser is not None:
                            await browser.close()
        except UtelRunCancelled:
            raise
        except UtelQaError as error:
            if post_submit_signal and error.stage.startswith(("inconcert_", "lead_balancer_")):
                error.args = (
                    f"{error} | Aviso del envío: {post_submit_signal}. No se reenvió el formulario.",
                )
            self.logger.exception("Fallo el flujo UTEL en %s", error.stage)
            self._append_failed_stage(len(self.stage_results) + 1, error, error.url, error.screenshot)
        except Exception as error:  # noqa: BLE001 - se devuelve un resumen apto para QA
            self.logger.exception("No se pudo completar el flujo UTEL")
            wrapped = UtelQaError("startup", self._friendly_error(error))
            self._append_failed_stage(len(self.stage_results) + 1, wrapped, page.url if page else None, None)

        return self._build_result(config, started_at, timer)

    def _build_result(self, config: UtelQaConfig, started_at: str, timer: float) -> dict[str, Any]:
        failed = any(stage.status == "FAIL" for stage in self.stage_results)
        finished_at = datetime.now().isoformat(timespec="seconds")
        if config.workflow_mode == "form_validation":
            if failed:
                summary = "La validacion del formulario o del lead fallo en una etapa."
            elif self.status_flags.get("lead_source") == "balanceador":
                summary = "Formulario enviado y enlace del lead verificado en el Balanceador."
            else:
                summary = "Formulario enviado y enlace del lead verificado en InConcert."
        else:
            if failed:
                summary = "El flujo UTEL/InConcert fallo en una etapa."
            elif self.status_flags.get("lead_source") == "balanceador":
                summary = "Lead localizado en el Balanceador; la conversion no se verifico en InConcert."
            else:
                summary = "Flujo UTEL/InConcert completado correctamente."
        if config.dry_run and not failed:
            summary = "Dry run completado: el formulario se lleno, pero no se envio ningun lead real."
            self.status_flags["utel_submission_message"] = "No enviado: dry run activo."
        return {
            "status": "FAIL" if failed else "PASS",
            "summary": summary,
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_seconds": round(perf_counter() - timer, 2),
            "country": config.country,
            "level": config.level,
            "modality": config.modality,
            "form_type": config.form_type,
            "lead_name": config.lead.name,
            "lead_email": config.lead.email,
            "lead_phone": config.lead.phone,
            "utel_submission_attempted": self._submission_attempted,
            "selected_program_name": self.selected_program_name,
            "program_selection_notice": self.program_selection_notice,
            "lead_url": self.lead_url,
            "environment": config.environment,
            "dry_run": config.dry_run,
            "workflow_mode": config.workflow_mode,
            **self.status_flags,
            "stages": self.stage_results,
            "screenshots": self.screenshots,
        }

    def _mark_submission_verified(self, signal: PostSubmitSignal | None) -> None:
        """Convierte una respuesta dudosa de UTEL en éxito solo si CRM la confirma."""

        if signal is None:
            return
        self.status_flags["utel_submission"] = "success"
        self.status_flags["utel_submission_message"] = (
            f"Lead verificado en CRM sin reenviar. Aviso original de UTEL: {signal}"
        )

    async def preflight_inconcert(self, config: UtelQaConfig) -> None:
        """Comprueba acceso real a InConcert antes de iniciar envíos por lote."""

        safe_config = config.model_copy(
            update={
                "dry_run": False,
                "defer_crm_verification": False,
                "verification_only": False,
                "keep_browser_open": False,
                "headless": True,
            }
        )
        self._validate_config(safe_config)
        try:
            from playwright.async_api import async_playwright
        except ImportError as error:
            raise UtelQaError(
                "inconcert_preflight",
                "No se inició ningún envío: Playwright no está instalado para validar InConcert.",
            ) from error

        await self._close_open_session()
        browser = None
        context = None
        keep_open = {"value": False}
        try:
            async with self._playwright(async_playwright, keep_open) as playwright:
                try:
                    if safe_config.browser == "chrome":
                        profile_directory = self.settings.storage_dir / "browser_profiles" / "chrome-qa"
                        profile_directory.mkdir(parents=True, exist_ok=True)
                        context = await playwright.chromium.launch_persistent_context(
                            str(profile_directory),
                            channel="chrome",
                            headless=safe_config.headless,
                            viewport={"width": 1440, "height": 900},
                        )
                    else:
                        browser_type = getattr(playwright, safe_config.browser)
                        browser = await browser_type.launch(headless=safe_config.headless)
                        context = await browser.new_context(viewport={"width": 1440, "height": 900})
                    page = await context.new_page()
                    page.set_default_timeout(30000)
                    await self._open_inconcert(page, safe_config)
                    await self._login_inconcert(page)
                    await self._open_contacts(page)
                finally:
                    # Cierra navegador y contexto antes de detener Playwright.
                    if context is not None:
                        with suppress(Exception):
                            await context.close()
                    if browser is not None:
                        with suppress(Exception):
                            await browser.close()
        except UtelQaError as error:
            raise UtelQaError(
                "inconcert_preflight",
                f"No se inició ningún envío: InConcert no superó la validación previa. {error}",
            ) from error
        except Exception as error:
            raise UtelQaError(
                "inconcert_preflight",
                "No se inició ningún envío: no fue posible validar el acceso a InConcert y Contactos.",
            ) from error

    @asynccontextmanager
    async def _playwright(self, async_playwright, keep_open: dict[str, bool]):
        playwright = await async_playwright().start()
        try:
            yield playwright
        finally:
            if not keep_open["value"]:
                await playwright.stop()

    @classmethod
    async def _close_open_session(cls) -> None:
        """Cierra una sesion visible que quedo abierta en una ejecucion anterior."""

        session = cls._open_session
        cls._open_session = None
        if not session:
            return
        try:
            if session.get("context") is not None:
                await session["context"].close()
            if session.get("browser") is not None:
                await session["browser"].close()
        except Exception:
            pass
        finally:
            try:
                await session["playwright"].stop()
            except Exception:
                pass

    async def _run_stage(
        self,
        number: int,
        stage: str,
        success_message: str,
        page: Any,
        action: Callable[[], Awaitable[Any]],
        screenshot_name: str | None = None,
    ) -> Any:
        """Ejecuta una etapa y registra su resultado legible."""

        try:
            value = await action()
            # Algunas acciones, como abrir Gestionar, pueden cambiar a una pestaña
            # nueva. Si la acción devuelve una Page de Playwright, la evidencia y
            # la URL de la etapa deben tomarse de esa pestaña y no del listado.
            result_page = (
                value
                if value is not None
                and hasattr(value, "url")
                and callable(getattr(value, "screenshot", None))
                else page
            )
            screenshot = (
                await self._safe_screenshot(result_page, screenshot_name)
                if screenshot_name
                else None
            )
            self.stage_results.append(
                UtelQaStageResult(
                    step_number=number,
                    stage=stage,
                    status="PASS",
                    message=success_message,
                    url=result_page.url,
                    screenshot=screenshot,
                )
            )
            return value
        except UtelRunCancelled:
            raise
        except Exception as error:  # noqa: BLE001 - Playwright emite errores variados
            failure = error if isinstance(error, UtelQaError) else UtelQaError(stage, self._friendly_error(error))
            # Capturar antes de que run() cierre el contexto del navegador. Si
            # la acción ya adjuntó la URL de la ficha, no la reemplazamos por la
            # URL del listado de Contactos.
            failure.url = failure.url or page.url
            failure_page = page
            if self.lead_url and self._is_inconcert_contact_detail(self.lead_url):
                for candidate in getattr(page.context, "pages", []):
                    if getattr(candidate, "url", "") == self.lead_url:
                        failure_page = candidate
                        break
            failure.screenshot = await self._safe_screenshot(
                failure_page,
                f"error_{failure.stage}",
            )
            if failure is error:
                raise
            raise failure from error

    async def _show_active_page(self, page: Any) -> None:
        """Trae al frente la pestaña que el Bot está procesando, sin afectar el flujo."""

        try:
            await page.bring_to_front()
        except Exception as error:  # noqa: BLE001 - el foco visual no es crítico
            self.logger.debug("No fue posible enfocar la pestaña activa del Bot: %s", error)

    async def _open_utel(self, page: Any, config: UtelQaConfig) -> None:
        direct_program = self._select_direct_doctorate_program(config)
        target_url = direct_program["url"] if direct_program else config.utel_url
        await page.goto(target_url, wait_until="domcontentloaded")
        await self._check_access(page)
        expected_program = direct_program.get("page_title", direct_program["text"]) if direct_program else config.program_name
        if expected_program:
            await self._validate_program_heading(page, expected_program)

    def _select_direct_doctorate_program(self, config: UtelQaConfig) -> dict[str, str] | None:
        """Selecciona una PDP directa para Doctorados de Leads Deploy."""

        leads_deploy = DoctorateLinkCatalog.is_leads_deploy_file(config.source_filename)
        if config.workflow_mode != "form_validation" or (config.form_type != "tarjeta" and not leads_deploy):
            return None
        level = config.navigation_level or config.level
        if not self._normalize(level).startswith("doctorado"):
            return None

        candidates = DoctorateLinkCatalog.programs(config.country)
        if not candidates:
            if leads_deploy:
                raise UtelQaError(
                    "utel_navigation",
                    f"El archivo '{config.source_filename}' exige ENLACE DIRECTO para todos los Doctorados, "
                    f"pero el catálogo compartido no contiene enlaces para {config.country}. "
                    "Agrega ese país y sus programas al archivo de enlaces directos.",
                )
            return None

        if config.program_name:
            selected = DoctorateLinkCatalog.resolve(config.country, config.program_name)
            if selected is None:
                available = ", ".join(candidate["text"] for candidate in candidates)
                raise UtelQaError(
                    "utel_navigation",
                    f"El programa '{config.program_name}' no existe en el catálogo directo de {config.country}. "
                    f"Disponibles: {available}.",
                )
        else:
            selected = self._rotate_program(candidates, config.utel_url, config)

        self.selected_program_name = selected["text"]
        self._selected_direct_url = selected["url"]
        self._selected_direct_page_program = selected.get("page_title", selected["text"])
        self.logger.info(
            "Doctorado directo seleccionado para %s: %s (%s)",
            config.country,
            selected["text"],
            selected["url"],
        )
        return selected

    async def _validate_program_heading(self, page: Any, expected_program: str) -> None:
        heading = page.locator("h1").first
        try:
            await heading.wait_for(state="visible", timeout=12000)
            actual_title = (await heading.inner_text()).strip()
        except Exception as error:
            raise UtelQaError(
                "utel_program_validation",
                "No se encontro el titulo H1 del programa en la URL indicada.",
                "h1",
            ) from error
        if self._normalize(actual_title) != self._normalize(expected_program):
            raise UtelQaError(
                "utel_program_validation",
                f"El programa no coincide. Esperado: '{expected_program}' | H1 encontrado: '{actual_title}'.",
                "h1",
            )

    async def _navigate_utel(self, page: Any, config: UtelQaConfig) -> None:
        if self._selected_direct_url:
            self.logger.info("PDP directa confirmada; se omite el clic desde el listado de programas.")
            return
        # Los Excel de programas normalmente contienen la URL PDP directa.
        # Si el H1 ya fue validado en _open_utel, no debemos volver a abrir el
        # menú global de Modalidad/Nivel: esas opciones también existen ocultas
        # en otras partes del DOM y pueden provocar un timeout.
        if config.program_name:
            heading = page.locator("h1").first
            if await heading.count() and await heading.is_visible():
                actual_title = (await heading.inner_text()).strip()
                if self._normalize(actual_title) == self._normalize(config.program_name):
                    self.logger.info("URL directa de programa confirmada por H1; se omite la navegación global.")
                    return
        if config.workflow_mode == "form_validation":
            await self._navigate_form_validation(page, config)
            return
        modalidad = page.get_by_text(re.compile(r"^Modalidad$", re.I)).first
        await self._hover_center(modalidad, page)
        modality_variants = self._spanish_variants(config.modality)
        modality_option = await self._text_locator(page, [*modality_variants, *[f"Modalidad {item}" for item in modality_variants]])
        await self._hover_center(modality_option, page)
        level_option = await self._text_locator(page, self._level_candidates(config.level))
        await self._hover_center(level_option, page)

        if config.program_selection_strategy == "exact_match":
            program_option = await self._text_locator(page, [config.program_name])
            await program_option.click()
            await page.wait_for_load_state("domcontentloaded")
            return

        first_program = await self._first_visible_program_link(page)
        if first_program is not None:
            await first_program.click()
            await page.wait_for_load_state("domcontentloaded")
            return

        await level_option.click()
        await page.wait_for_load_state("domcontentloaded")

    async def _navigate_form_validation(self, page: Any, config: UtelQaConfig) -> None:
        """Navega el menu de Leads Deploy y elige el primer programa disponible."""

        # Las URLs de Leads Deploy ya apuntan a la superficie correcta. Footer
        # vive en la pagina recibida y Lateral se abre despues desde el CTA.
        # Tarjeta es la unica ubicacion que necesita entrar primero a una PDP.
        if config.form_type in {"footer", "lateral"}:
            return
        if config.form_type == "tarjeta":
            await self._click_first_program_card(page)
            await page.wait_for_load_state("domcontentloaded")
            await self._capture_selected_program(page)
            return

        modal_menu = page.get_by_text(re.compile(r"^Modalidad$", re.I)).first
        if await modal_menu.count() and await modal_menu.is_visible():
            await self._hover_center(modal_menu, page)
            modality_option = await self._text_locator(
                page,
                self._menu_candidates(config.navigation_modality or config.modality),
            )
            await self._hover_center(modality_option, page)
            level_option = await self._text_locator(
                page,
                self._menu_candidates(config.navigation_level or config.level),
            )
            await self._hover_center(level_option, page)
            target_option = level_option
            if config.navigation_sublevel:
                try:
                    target_option = await self._text_locator(
                        page,
                        self._menu_candidates(config.navigation_sublevel),
                    )
                    await self._hover_center(target_option, page)
                except UtelQaError:
                    self.logger.info(
                        "El submenu %s no existe; se usara %s.",
                        config.navigation_sublevel,
                        config.navigation_level,
                    )

            first_program = await self._first_visible_program_link(page, target_option)
            if first_program is not None:
                await first_program.click()
            else:
                await target_option.click()
            await page.wait_for_load_state("domcontentloaded")
            await self._capture_selected_program(page)
            return

        # Algunos portales por pais reemplazan "Modalidad" por "Oferta
        # educativa". En esos sitios el nivel abre una pagina de resultados y
        # el programa se elige desde la primera card visible.
        education_menu = page.get_by_text(re.compile(r"^Oferta educativa$", re.I)).first
        if await education_menu.count() and await education_menu.is_visible():
            await self._hover_center(education_menu, page)
            level_option = await self._text_locator(
                page,
                self._education_level_candidates(config.navigation_level or config.level),
            )
            await level_option.click()
            await page.wait_for_load_state("domcontentloaded")
            await self._click_first_program_card(page)
            await page.wait_for_load_state("domcontentloaded")
            await self._capture_selected_program(page)
            return

        # Global/Filipinas ofrece Bachelor/Master directamente y no muestra
        # el menu Modalidad utilizado por los sitios en espanol.
        level_option = await self._text_locator(
            page,
            self._menu_candidates(config.navigation_level or config.level),
        )
        await level_option.click()
        await page.wait_for_load_state("domcontentloaded")
        await self._capture_selected_program(page)

    async def _click_first_program_card(self, page: Any) -> None:
        """Rota programas del listado y abre su CTA Explorar cuando existe."""

        cards = page.locator(".chakra-card__body:visible")
        try:
            await cards.first.wait_for(state="visible", timeout=18000)
        except Exception:
            cards = None

        if cards is not None:
            candidates = []
            for index in range(await cards.count()):
                card = cards.nth(index)
                program_text = card.locator("p").first
                label = (await program_text.inner_text()).strip() if await program_text.count() else ""
                if not label:
                    continue
                explore = card.get_by_text(re.compile(r"^(Explorar|Ver programa|Conocer mas|Conocer m[aá]s)$", re.I)).first
                link = card.locator("xpath=ancestor::a[1]")
                if not await link.count():
                    link = card.locator("a[href]").first
                target = explore if await explore.count() and await explore.is_visible() else link
                if not await target.count() or not await target.is_visible():
                    continue
                candidates.append({"text": label, "target": target})
            if candidates:
                selected = self._rotate_program(candidates, page.url)
                self.selected_program_name = selected["text"]
                await selected["target"].scroll_into_view_if_needed()
                await selected["target"].click()
                return

        # Las paginas nuevas no siempre usan chakra-card. Como respaldo,
        # seleccionamos el primer enlace academico visible dentro de <main>.
        current_path = urlparse(page.url).path.rstrip("/").lower()
        links = page.locator("main a[href]:visible")
        academic_path = re.compile(
            r"/(doctorado|maestr|master|magister|licenciatura|carrera|bachelor|bootcamp|diplomado|especialidad)[^/]*",
            re.I,
        )
        candidates = []
        for index in range(await links.count()):
            link = links.nth(index)
            href = (await link.get_attribute("href") or "").strip()
            candidate_path = urlparse(href).path.rstrip("/").lower()
            if not candidate_path or candidate_path == current_path or not academic_path.search(candidate_path):
                continue
            label = (await link.inner_text()).strip()
            if not label or re.fullmatch(r"conocer m[aá]s|explorar|ver programa", label, re.I):
                label = candidate_path
            candidates.append({"text": label, "target": link})
        if candidates:
            selected = self._rotate_program(candidates, page.url)
            await selected["target"].scroll_into_view_if_needed()
            await selected["target"].click()
            return

        raise UtelQaError(
            "utel_navigation",
            "El listado se abrio, pero no se encontro una tarjeta o enlace valido de programa.",
            ".chakra-card__body, main a[href]",
        )

    async def _capture_selected_program(self, page: Any) -> None:
        await self._check_access(page)
        heading = page.locator("h1:visible").first
        if await heading.count():
            self.selected_program_name = (await heading.inner_text()).strip()

    async def _check_access(self, page: Any) -> None:
        text = await page.locator("body").inner_text(timeout=12000)
        if re.search(r"sorry,?\s+you have been blocked|you are unable to access", text, re.I):
            raise UtelQaError(
                "utel_access", "El sitio bloqueo el acceso de esta sesion. No se envio el formulario. "
                "Que abra manualmente no confirma acceso desde el navegador del bot; revisar la captura y la sesion.", "body",
            )

    async def _find_utel_form(self, page: Any, config: UtelQaConfig) -> Any:
        await self._check_access(page)
        form_id = self.FORM_IDS[config.form_type]
        selector = f"#{form_id}"
        if config.form_type == "lateral":
            try:
                await self._open_lateral_form(page)
            except Exception as error:
                raise UtelQaError(
                    "utel_form",
                    "No se pudo abrir el formulario lateral con el boton Solicitar informacion.",
                    "text=Solicitar informacion",
                ) from error

        form, form_count = await self._wait_for_visible_form(page, selector)
        reloaded = False
        if form is None and config.form_type == "tarjeta":
            # En varias PDP el formulario React aparece justo cuando vence la
            # espera. Una recarga antes de rellenar todavía es segura y evita
            # clasificar esa demora como un formulario inexistente.
            reloaded = True
            self.logger.warning(
                "El formulario %s no estuvo listo en %s segundos; se recargara una vez.",
                form_id,
                self.FORM_WAIT_TIMEOUT_MS // 1000,
            )
            await page.reload(wait_until="domcontentloaded", timeout=self.FORM_WAIT_TIMEOUT_MS)
            await self._check_access(page)
            expected_page_program = self._selected_direct_page_program or self.selected_program_name
            if expected_page_program:
                await self._validate_program_heading(page, expected_page_program)
            form, form_count = await self._wait_for_visible_form(page, selector)

        if form is None:
            retry_text = " despues de una recarga" if reloaded else ""
            if form_count:
                message = (
                    f"El formulario {form_id} existe, pero no se hizo visible en "
                    f"{self.FORM_WAIT_TIMEOUT_MS // 1000} segundos{retry_text}."
                )
            else:
                message = (
                    f"El formulario {form_id} no aparecio en el DOM en "
                    f"{self.FORM_WAIT_TIMEOUT_MS // 1000} segundos{retry_text}."
                )
            raise UtelQaError("utel_form", message, selector)

        if config.form_type == "footer":
            # Solo el footer requiere ser llevado a la zona inferior. La tarjeta
            # aparece en el hero de la PDP y hacer scroll allí puede fallar
            # mientras React termina de estabilizar la página.
            await form.scroll_into_view_if_needed()
            await asyncio.sleep(2)
            refreshed_form, refreshed_count = await self._wait_for_visible_form(
                page,
                selector,
                timeout_ms=self.FORM_RECHECK_TIMEOUT_MS,
            )
            if refreshed_form is None:
                state = "existe, pero dejo de estar visible" if refreshed_count else "desaparecio del DOM"
                raise UtelQaError(
                    "utel_form",
                    f"El formulario {form_id} {state} despues de activar el contenido de la pagina.",
                    selector,
                )
            form = refreshed_form
        return form

    async def _wait_for_visible_form(
        self,
        page: Any,
        selector: str,
        timeout_ms: int | None = None,
    ) -> tuple[Any | None, int]:
        """Reconsulta el DOM para tolerar nodos React que se remontan al cargar."""

        wait_ms = timeout_ms or self.FORM_WAIT_TIMEOUT_MS
        deadline = perf_counter() + (wait_ms / 1000)
        last_count = 0
        while perf_counter() < deadline:
            form = page.locator(selector).first
            try:
                last_count = await asyncio.wait_for(form.count(), timeout=3)
                if last_count and await asyncio.wait_for(form.is_visible(), timeout=3):
                    return form, last_count
            except Exception:  # El nodo puede desaparecer mientras React lo sustituye.
                pass
            remaining = deadline - perf_counter()
            if remaining > 0:
                await asyncio.sleep(min(self.FORM_POLL_INTERVAL_SECONDS, remaining))
        return None, last_count

    async def _open_lateral_form(self, page: Any) -> None:
        """Abre el formulario lateral cuando la pagina lo mantiene cerrado."""

        controls = page.locator('button:visible, a:visible, [role="button"]:visible')
        accepted_prefixes = (
            "solicitar informaci",
            "solicita informaci",
            "quiero informaci",
            "pedir informaci",
        )
        for index in range(await controls.count()):
            control = controls.nth(index)
            label = self._normalize((await control.inner_text()).strip())
            if label.startswith(accepted_prefixes):
                await control.scroll_into_view_if_needed()
                await control.click()
                form, _ = await self._wait_for_visible_form(page, "#LateralBLC")
                if form is not None:
                    return
        form = page.locator("#LateralBLC").first
        if await form.count() and await form.is_visible():
            # Algunas paginas conservan el drawer abierto entre navegaciones.
            return
        raise UtelQaError(
            "utel_form",
            "El formulario lateral esta cerrado y no se encontro el boton Solicitar informacion.",
            "button:has-text('Solicitar informacion')",
        )

    async def _fill_utel_form(self, page: Any, form: Any, config: UtelQaConfig) -> None:
        academic_values: list[dict[str, str]] = []
        if config.skip_preselected_fields:
            self.logger.info("Fila marcada como 'Nuevos productos': se omite selección de modalidad/nivel/programa.")
            self.selected_program_name = config.program_name or self.selected_program_name
        else:
            await self._set_dynamic_field(form, '[data-cy="formModalityInput"]', config.modality)
            await self._set_dynamic_field(form, '[data-cy="educationLevelInput"]', config.level)
            rotate_philippines_master = self._should_rotate_philippines_master(config)
            if config.program_name:
                # Normalmente UTEL recibe el producto seleccionado desde la URL
                # directa. Si falla esa preselección, se recupera usando el nombre
                # del Excel; el selector ya contempla el nombre sin nivel.
                await self._recover_missing_program_selection(form, config)
            else:
                if rotate_philippines_master:
                    # El H1 del listado puede contener "Master's Degree", pero no
                    # representa uno de los programas disponibles en el lateral.
                    self.selected_program_name = ""
                await self._select_random_program(page, form, '[data-cy="productsInput"]', config)
            academic_values = await self._academic_values(form)
        await self._select_optional_bachillerato(form)
        await self._select_random_city(form)
        await self._select_preferred_contact_channel(form)
        await self._fill_first_available(form, ['[data-cy="textfieldInput"]', '#first_name', 'input[name="first_name"]'], config.lead.name)
        await self._fill_first_available(form, ['[data-cy="emailInput"]', '#email', 'input[type="email"]', 'input[name="email"]'], config.lead.email)
        await self._set_country_if_possible(form, config.country)
        await self._fill_first_available(form, ['[data-cy="telephoneInput"]', '#phone', 'input[type="tel"]', 'input[name="phone"]'], config.lead.phone)
        await self._check_privacy(form)
        if academic_values and academic_values != await self._academic_values(form):
            raise UtelQaError(
                "utel_fill",
                "El sitio reinicio la modalidad, el nivel o el programa durante el llenado. No se enviara el formulario.",
                '[data-cy="formModalityInput"], [data-cy="educationLevelInput"], [data-cy="productsInput"]',
            )

    async def _recover_missing_program_selection(self, form: Any, config: UtelQaConfig) -> None:
        """Selecciona el programa solo cuando UTEL no lo dejó preseleccionado."""

        selector = '[data-cy="productsInput"]'
        field = form.locator(selector).first
        if not await field.count():
            # Algunos formularios no exponen el campo porque la PDP ya fija el
            # producto internamente. Conservamos el comportamiento existente.
            self.selected_program_name = config.program_name
            return

        current_value = (await field.input_value()).strip()
        if current_value:
            self.selected_program_name = config.program_name
            return

        # _set_dynamic_field busca primero el texto completo y luego la versión
        # sin prefijo académico: “Maestría en Ingeniería…” -> “Ingeniería…”.
        await self._set_dynamic_field(form, selector, config.program_name)
        selected_value = (await field.input_value()).strip()
        if not selected_value:
            raise UtelQaError(
                "utel_fill",
                f"UTEL no preseleccionó ni permitió seleccionar el programa '{config.program_name}'.",
                selector,
            )

        self.selected_program_name = config.program_name
        self.program_selection_notice = (
            "Incidencia corregida: UTEL abrió el campo Programa de interés sin "
            f"preselección; el Bot seleccionó automáticamente '{config.program_name}'."
        )
        self.logger.warning(self.program_selection_notice)

    def _should_rotate_philippines_master(self, config: UtelQaConfig) -> bool:
        """Rota los másteres del lateral filipino cuando Excel no fija programa."""

        level = self._normalize(config.navigation_level or config.level)
        return (
            not config.program_name
            and self._normalize(config.country) in {"filipinas", "philippines"}
            and config.form_type == "lateral"
            and level.startswith("master")
        )

    async def _academic_values(self, form: Any) -> list[dict[str, str]]:
        return await form.locator(
            '[data-cy="formModalityInput"], [data-cy="educationLevelInput"], [data-cy="productsInput"]'
        ).evaluate_all("els => els.map(e => ({field: e.dataset.cy, value: e.value}))")

    def _rotate_program(self, candidates: list[dict], url: str, config: UtelQaConfig | None = None) -> dict:
        config = config or self._rotation_config
        scope = [config.country, config.level, config.modality, config.form_type,
                 "dry_run" if config.dry_run else "real"] if config else [urlparse(url).path]
        scope.insert(0, urlparse(url).netloc)
        selected = ProgramRotationService(self.settings.database_path).choose(scope, candidates)
        self.logger.info("Rotacion de programas: %s (%s candidatos disponibles). Es un intento, no una aprobacion.", selected["text"], len(candidates))
        return selected

    async def _select_random_program(self, page: Any, form: Any, selector: str, config: UtelQaConfig) -> None:
        """Rota programas disponibles en select o autocomplete."""

        field = form.locator(selector).first
        if not await field.count():
            return
        tag_name = await field.evaluate("(element) => element.tagName.toLowerCase()")
        if tag_name == "input":
            await self._select_random_autocomplete_option(page, form, field, selector, config)
            return
        if tag_name != "select":
            raise UtelQaError("utel_fill", "El campo de programa no es seleccionable.", selector)
        await field.wait_for(state="visible", timeout=12000)
        await self._wait_for_select_options(field)
        options = await field.evaluate(
            """(element) => [...element.options]
                .filter((option) => option && !option.disabled && option.value
                    && !/seleccion|programa de interes|programa de interés|cargando|loading|please select|select an option/i.test(option.textContent || ''))
                .map((option) => ({ value: option.value, text: option.textContent || '' }))"""
        )
        if not options:
            raise UtelQaError("utel_fill", "El formulario no contiene programas disponibles.", selector)
        selected = self._rotate_program(options, page.url, config)
        await field.select_option(value=selected["value"])
        await asyncio.sleep(1)
        if await field.input_value() != selected["value"]:
            raise UtelQaError("utel_fill", "El programa seleccionado fue reiniciado por el sitio.", selector)
        self.selected_program_name = selected["text"].strip()

    async def _select_random_autocomplete_option(
        self, page: Any, form: Any, field: Any, selector: str, config: UtelQaConfig
    ) -> None:
        # El cambio de modalidad/nivel inicia la carga de programas con un
        # pequeño retraso. Esperamos a que el ciclo Cargando... haya terminado
        # y el placeholder permanezca estable antes de escribir la búsqueda.
        await asyncio.sleep(1.5)
        deadline = perf_counter() + 30
        ready_checks = 0
        while perf_counter() < deadline:
            placeholder = self._normalize(await field.get_attribute("placeholder") or "")
            if "cargando" not in placeholder and "loading" not in placeholder:
                ready_checks += 1
                if ready_checks >= 3:
                    break
            else:
                ready_checks = 0
            await asyncio.sleep(0.5)
        else:
            raise UtelQaError("utel_fill", "El campo de programa no termino de cargar.", selector)

        results = form.locator('[id^="result-"]')
        available = []
        await field.focus()
        toggle = field.locator("xpath=following-sibling::*[1]")
        if await toggle.count():
            try:
                await toggle.click(force=True)
                toggle_deadline = perf_counter() + 5
                while perf_counter() < toggle_deadline:
                    items = await results.evaluate_all(
                        """elements => elements
                            .filter(element => {
                                const rect = element.getBoundingClientRect();
                                const style = getComputedStyle(element);
                                return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden';
                            })
                            .map(element => ({ id: element.id, text: (element.innerText || element.textContent || '').trim() }))"""
                    )
                    available = [
                        item for item in items
                        if item.get("text") and not re.search(r"cargando|sin resultados|selecciona", item["text"], re.I)
                    ]
                    if available:
                        break
                    await asyncio.sleep(0.4)
            except Exception:
                available = []
        # Estos autocompletados no siempre muestran el catálogo al enfocarse;
        # necesitan al menos una letra. Se aleatoriza la consulta y después la
        # opción para evitar usar siempre el mismo programa.
        probes = list("aeiourst")
        secrets.SystemRandom().shuffle(probes)
        for probe in (probes if not available else []):
            await field.fill(probe)
            deadline = perf_counter() + 8
            while perf_counter() < deadline:
                items = await results.evaluate_all(
                    """elements => elements
                        .filter(element => {
                            const rect = element.getBoundingClientRect();
                            const style = getComputedStyle(element);
                            return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden';
                        })
                        .map(element => ({ id: element.id, text: (element.innerText || element.textContent || '').trim() }))"""
                )
                available = [
                    item for item in items
                    if item.get("text") and not re.search(r"cargando|sin resultados|selecciona", item["text"], re.I)
                ]
                if available:
                    break
                await asyncio.sleep(0.4)
            if available:
                break
        if not available:
            raise UtelQaError(
                "utel_fill",
                f"El autocomplete no mostro programas disponibles. Selecciones actuales: {await self._academic_values(form)}.",
                selector,
            )
        selected = self._rotate_program(available, page.url, config)
        clicked = await results.evaluate_all(
            """(elements, wanted) => {
                const option = elements.find(element => element.id === wanted.id && (element.innerText || element.textContent || '').trim() === wanted.text);
                if (!option) return false;
                option.click();
                return true;
            }""",
            selected,
        )
        if not clicked:
            raise UtelQaError("utel_fill", "El programa elegido desaparecio antes de seleccionarse.", selector)
        await asyncio.sleep(0.8)
        if (self._normalize(await field.input_value()) != self._normalize(selected["text"])
                or await form.locator('[id^="result-"]:visible').count()):
            raise UtelQaError("utel_fill", "El programa se mostro, pero no quedo seleccionado en el formulario.", selector)
        self.selected_program_name = selected["text"]

    async def _wait_for_select_options(self, field: Any, timeout_seconds: int = 30) -> None:
        deadline = perf_counter() + timeout_seconds
        while perf_counter() < deadline:
            ready = await field.evaluate(
                """(element) => [...element.options].some((option) =>
                    option.value && !option.disabled && !/cargando|loading/i.test(option.textContent || '')
                )"""
            )
            if ready:
                return
            await asyncio.sleep(0.5)
        raise UtelQaError("utel_fill", "El formulario no termino de cargar sus opciones.")

    async def _select_optional_bachillerato(self, form: Any) -> None:
        """Marca SI cuando el formulario pregunta si terminó el bachillerato."""

        selects = form.locator("select")
        for index in range(await selects.count()):
            select = selects.nth(index)
            candidate = await select.evaluate(
                """(element) => {
                    const normalize = (value) => String(value || '').toLowerCase().normalize('NFD').replace(/[\\u0300-\\u036f]/g, '').replace(/\\s+/g, ' ').trim();
                    const context = element.closest('label, .form-group, .chakra-form-control, div')?.innerText || element.parentElement?.innerText || '';
                    const option = [...element.options].find((item) => normalize(item.textContent) === 'si');
                    return { context: normalize(context), value: option?.value || null };
                }"""
            )
            if candidate.get("value") and re.search(
                r"bachiller|grado\s*11|graduaste|terminado.*estudios|estudios.*terminado",
                candidate.get("context", ""),
                re.I,
            ):
                await select.select_option(value=candidate["value"])
                return

    async def _select_random_city(self, form: Any) -> None:
        """Selecciona una ciudad aleatoria cuando el formulario la solicita."""

        fields = form.locator("select")
        for index in range(await fields.count()):
            field = fields.nth(index)
            if not await field.is_visible() or not await field.is_enabled():
                continue
            metadata = await field.evaluate("""element => [element.name, element.id,
                element.dataset.cy, element.getAttribute('aria-label'),
                ...Array.from(element.labels || []).map(label => label.textContent),
                element.options[0]?.textContent].filter(Boolean).join(' ')""")
            if re.search(r"ciudad|city|provincia|province|estado|state", metadata, re.I):
                await self._select_random_select_option(field, "Ciudad / provincia / estado")

    async def _select_preferred_contact_channel(self, form: Any) -> None:
        """Selecciona Cualquier canal en formularios con canal preferido."""

        fields = form.locator('select[name="Canal_Preferido"], select[name*="canal" i], select[name*="channel" i]')
        if not await fields.count():
            return
        field = fields.first
        options = await field.locator("option").evaluate_all(
            "elements => elements.map(option => ({ text: option.textContent || '', value: option.value || '' }))"
        )
        selected = next(
            (
                option for option in options
                if self._normalize(option["text"]) in {"cualquier canal", "any channel"}
                or self._normalize(option["value"]) in {"cualquier canal", "any channel"}
            ),
            None,
        )
        if not selected:
            raise UtelQaError(
                "utel_fill", "El formulario pide un canal de contacto, pero no ofrece Cualquier canal."
            )
        await field.select_option(value=selected["value"])

    async def _select_random_select_option(self, field: Any, label: str) -> None:
        await field.wait_for(state="visible", timeout=12000)
        await self._wait_for_select_options(field)
        options = await field.locator("option").evaluate_all(
            r"""elements => elements
                .filter(option => !option.disabled && option.value
                    && !/^\s*(seleccion|elige|cargando|loading|ciudad\s*:|provincia\s*:|estado\s*:)/i.test(option.textContent || ''))
                .map(option => ({ text: option.textContent || '', value: option.value || '' }))"""
        )
        if not options:
            raise UtelQaError("utel_fill", f"El campo {label} no contiene opciones disponibles.")
        selected = secrets.choice(options)
        await field.select_option(value=selected["value"])

    async def _stable_utel_submit_context(
        self,
        page: Any,
        original_form: Any,
        submit_selector: str,
    ) -> tuple[Any, Any]:
        """Re-resuelve formulario/botón cuando React remonta TarjetaBLC antes del envío."""

        last_error: Exception | None = None
        form_selector = ", ".join(f"#{form_id}:visible" for form_id in self.FORM_IDS.values())

        for attempt in range(5):
            candidates: list[Any] = []

            # Primero se intenta el locator original. Si React reemplazó el nodo,
            # Playwright normalmente lo re-resuelve; si no, usamos el formulario
            # visible actual de la página.
            try:
                if await original_form.count() and await original_form.is_visible():
                    candidates.append(original_form)
            except Exception as error:
                last_error = error

            try:
                visible_forms = page.locator(form_selector)
                for index in range(await visible_forms.count()):
                    candidate = visible_forms.nth(index)
                    if all(candidate is not current for current in candidates):
                        candidates.append(candidate)
            except Exception as error:
                last_error = error

            for candidate in candidates:
                try:
                    await candidate.wait_for(state="visible", timeout=5000)
                    submit = candidate.locator(submit_selector).first
                    await submit.wait_for(state="visible", timeout=5000)

                    # El botón puede estar unos instantes deshabilitado mientras
                    # React termina de aplicar país/programa/consentimiento.
                    if not await submit.is_enabled():
                        last_error = RuntimeError(
                            "El botón de envío todavía está deshabilitado."
                        )
                        continue

                    await self._validate_utel_form_before_submit(candidate)
                    return candidate, submit
                except UtelQaError as error:
                    # Un campo realmente inválido sí debe detener el envío.
                    if error.stage == "utel_fill":
                        raise
                    last_error = error
                except Exception as error:
                    last_error = error

            if attempt < 4:
                await asyncio.sleep(1.25)

        detail = self._friendly_error(last_error) if last_error else "formulario no disponible"
        raise UtelQaError(
            "utel_submit",
            "UTEL reconstruyó el formulario o el botón de envío y no logró "
            f"estabilizarlo después de 5 intentos. Detalle: {detail}",
            submit_selector,
        ) from last_error

    async def _submit_utel_form(
        self,
        page: Any,
        form: Any,
        should_stop: Callable[[], bool] | None = None,
    ) -> None:
        """Envía UTEL y solo confirma el intento al observar POST /api/forms."""

        submit_selector = 'button[type="submit"], input[type="submit"]'
        form, submit = await self._stable_utel_submit_context(
            page,
            form,
            submit_selector,
        )

        # Último punto seguro: si la detención llegó antes del POST, no se crea lead.
        self._raise_if_stop_requested(should_stop)
        await self._show_active_page(page)
        await asyncio.sleep(0.25)

        loop = asyncio.get_running_loop()
        api_request = loop.create_future()
        api_response = loop.create_future()
        network_failures: list[str] = []
        observed_post_paths: list[str] = []

        def is_utel_form_request(request: Any) -> bool:
            try:
                parsed = urlparse(str(request.url))
                return (
                    str(request.method).upper() == "POST"
                    and parsed.path.rstrip("/").casefold().endswith("/api/forms")
                )
            except Exception:
                return False

        def capture_request(request: Any) -> None:
            try:
                if str(request.method).upper() == "POST":
                    parsed = urlparse(str(request.url))
                    observed_post_paths.append(f"{parsed.netloc}{parsed.path}")
                if is_utel_form_request(request) and not api_request.done():
                    api_request.set_result(request)
            except Exception:
                return

        def capture_response(response: Any) -> None:
            try:
                request = response.request
                if is_utel_form_request(request) and not api_response.done():
                    api_response.set_result(response)
            except Exception:
                return

        def capture_failed_request(request: Any) -> None:
            try:
                parsed = urlparse(str(request.url))
                if parsed.netloc == "api.ipify.org" or is_utel_form_request(request):
                    failure = str(request.failure or "fallo de red")
                    network_failures.append(f"{parsed.netloc}{parsed.path}: {failure}")
            except Exception:
                return

        listeners_installed = False
        try:
            page.on("request", capture_request)
            page.on("response", capture_response)
            page.on("requestfailed", capture_failed_request)
            listeners_installed = True
        except Exception as error:
            raise UtelQaError(
                "utel_submit",
                "No fue posible activar la verificación de red antes del envío. "
                "El formulario no se enviará sin poder confirmar POST /api/forms.",
                submit_selector,
            ) from error

        feedback_task: asyncio.Task[str] | None = None
        try:
            await submit.scroll_into_view_if_needed()

            # Un solo clic real de Playwright. force=True evita que una animación
            # del drawer impida la acción, pero conserva el evento de usuario.
            click_error: Exception | None = None
            try:
                await submit.click(force=True, timeout=12000)
            except Exception as error:
                # El request puede haberse emitido justo antes de que Playwright
                # reportara un cambio de página o de nodo; se comprueba antes de fallar.
                click_error = error

            request_deadline = perf_counter() + 15
            while not api_request.done():
                self._raise_if_stop_requested(should_stop)
                remaining = request_deadline - perf_counter()
                if remaining <= 0:
                    unique_posts = list(dict.fromkeys(observed_post_paths))[-5:]
                    observed = (
                        f" POST observados: {', '.join(unique_posts)}."
                        if unique_posts
                        else " No se observó ninguna solicitud POST desde la página."
                    )
                    cause = click_error or asyncio.TimeoutError(
                        "No se observó POST /api/forms después del clic."
                    )
                    raise UtelQaError(
                        "utel_submit",
                        "El botón Enviar información fue accionado, pero UTEL no "
                        "generó POST /api/forms. El formulario no se considera "
                        "enviado y no se buscará el lead en InConcert ni en "
                        f"Balanceador.{observed}",
                        submit_selector,
                    ) from cause
                await asyncio.sleep(min(0.25, remaining))

            # A partir de aquí existe evidencia de que la petición salió del navegador.
            api_request.result()
            self._submission_attempted = True

            feedback_task = asyncio.create_task(
                self._wait_for_utel_submit_feedback(page)
            )
            response_deadline = perf_counter() + 65
            done: set[asyncio.Future] = set()
            while not done:
                self._raise_if_stop_requested(should_stop)
                remaining = response_deadline - perf_counter()
                if remaining <= 0:
                    break
                done, _ = await asyncio.wait(
                    {api_response, feedback_task},
                    timeout=min(0.25, remaining),
                    return_when=asyncio.FIRST_COMPLETED,
                )

            if api_response in done:
                await self._classify_utel_api_response(api_response.result())
                return

            text = ""
            if feedback_task in done:
                with suppress(Exception):
                    text = feedback_task.result()

            if text and re.search(
                rf"(?:{self._last_submit_error_pattern})|debe\s+ingresar.*v[aá]lid|valor\s+v[aá]lido",
                text,
                re.I,
            ):
                # El response suele llegar casi al mismo tiempo que el aviso visual.
                response = None
                grace_deadline = perf_counter() + 2
                while not api_response.done() and perf_counter() < grace_deadline:
                    self._raise_if_stop_requested(should_stop)
                    await asyncio.sleep(0.1)
                if api_response.done() and not api_response.cancelled():
                    response = api_response.result()
                if response is not None:
                    await self._classify_utel_api_response(response)
                    return
                raise RejectedSubmission(
                    "utel_submit",
                    f"UTEL mostró un aviso después del POST: {text}",
                )

            if text and re.search(self._utel_success_pattern(), text, re.I):
                return

            if text and not api_response.done():
                grace_deadline = perf_counter() + 2
                while not api_response.done() and perf_counter() < grace_deadline:
                    self._raise_if_stop_requested(should_stop)
                    await asyncio.sleep(0.1)
                if api_response.done() and not api_response.cancelled():
                    await self._classify_utel_api_response(api_response.result())
                    return

            details = ""
            if network_failures:
                details = " Fallos de red observados: " + " | ".join(
                    network_failures[-3:]
                )
            raise UnconfirmedSubmission(
                "utel_submit",
                "POST /api/forms observado, pero UTEL no produjo una respuesta "
                "concluyente en 65 segundos. El lead podría haberse enviado; "
                f"se verificará en CRM sin reenviar.{details}",
                "#chakra-toast-manager-bottom",
            )
        except (PostSubmitSignal, UtelRunCancelled, UtelQaError):
            raise
        except Exception as error:
            if self._submission_attempted:
                raise UnconfirmedSubmission(
                    "utel_submit",
                    "Se observó POST /api/forms, pero no se pudo interpretar la "
                    "respuesta posterior. Se verificará en CRM sin reenviar.",
                    "#chakra-toast-manager-bottom",
                ) from error
            raise UtelQaError(
                "utel_submit",
                "No se pudo completar el clic y no se observó POST /api/forms. "
                "No se consultará CRM.",
                submit_selector,
            ) from error
        finally:
            if feedback_task is not None and not feedback_task.done():
                feedback_task.cancel()
                with suppress(asyncio.CancelledError):
                    await feedback_task
            elif feedback_task is not None:
                with suppress(asyncio.CancelledError, Exception):
                    feedback_task.result()
            if not api_request.done():
                api_request.cancel()
            if not api_response.done():
                api_response.cancel()
            if listeners_installed:
                with suppress(Exception):
                    page.remove_listener("request", capture_request)
                    page.remove_listener("response", capture_response)
                    page.remove_listener("requestfailed", capture_failed_request)

    async def _wait_for_utel_submit_feedback(self, page: Any) -> str:
        """Espera toast, validación inline o estado accesible tras el clic."""

        feedback_handle = await page.wait_for_function(
            """() => {
                const selectors = [
                  '#chakra-toast-manager-bottom',
                  '[role="alert"]',
                  '[role="status"]',
                  '.chakra-alert',
                  '.chakra-toast',
                  '.chakra-form__error-message',
                  '[data-invalid]'
                ];
                const text = selectors
                  .flatMap(selector => [...document.querySelectorAll(selector)])
                  .filter(element => element.getClientRects().length)
                  .map(element => (element.innerText || element.textContent || element.parentElement?.innerText || '').trim())
                  .find(value => /env[ií]o|gracias|recib|contactaremos|error|soporte|inv[aá]lid|valor v[aá]lido|obligatori|requerid|fall/i.test(value));
                return text || null;
            }""",
            timeout=60000,
        )
        json_value = getattr(feedback_handle, "json_value", None)
        if callable(json_value):
            value = await json_value()
            if isinstance(value, str) and value.strip():
                return value.strip()
        toast = page.locator("#chakra-toast-manager-bottom")
        return (await toast.inner_text()).strip()

    async def _classify_utel_api_response(self, response: Any) -> None:
        """Interpreta la respuesta real sin registrar correos ni teléfonos."""

        status = int(getattr(response, "status", 0) or 0)
        if 200 <= status < 300:
            return
        body = ""
        try:
            body = await response.text()
        except Exception:
            body = ""
        diagnostic = self._sanitize_submit_diagnostic(body)
        suffix = f" Detalle: {diagnostic}" if diagnostic else ""
        if status >= 500:
            raise UnconfirmedSubmission(
                "utel_submit",
                f"UTEL devolvió HTTP {status or 'desconocido'} en POST /api/forms. "
                f"Se verificará en CRM porque el lead podría haberse enviado.{suffix}",
            )
        raise RejectedSubmission(
            "utel_submit",
            f"UTEL rechazó POST /api/forms con HTTP {status or 'desconocido'}.{suffix}",
        )

    def _utel_success_pattern(self) -> str:
        """Agrupa las variantes de confirmación conocidas de los portales UTEL."""

        pattern = (
            r"env[ií]o correcto|pronto recibir[aá]s informaci[oó]n|"
            r"successfully submitted|your information has been received|"
            r"gracias.*(?:registro|informaci[oó]n|solicitud)|"
            r"hemos recibido|(?:datos|solicitud|informaci[oó]n).*(?:recibid|enviad)|"
            r"te contactaremos|nos pondremos en contacto"
        )
        if self._last_submit_success_pattern:
            pattern += "|(?:" + self._last_submit_success_pattern + ")"
        return pattern

    @staticmethod
    def _sanitize_submit_diagnostic(value: str) -> str:
        """Elimina posibles datos del lead y limita el texto guardado en logs."""

        text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[email oculto]", str(value or ""))
        text = re.sub(r"(?<!\d)\+?\d[\d\s().-]{6,}\d(?!\d)", "[número oculto]", text)
        return re.sub(r"\s+", " ", text).strip()[:500]

    async def _validate_utel_form_before_submit(self, form: Any) -> None:
        """Detiene errores HTML reales y tolera remontajes transitorios de React."""

        invalid = None
        last_error: Exception | None = None

        for attempt in range(5):
            try:
                await form.wait_for(state="visible", timeout=5000)
                # Se crea el locator dentro de cada intento. TarjetaBLC puede
                # sustituir todo su árbol después de cambiar programa o país.
                controls = form.locator("input, select, textarea")
                invalid = await controls.evaluate_all(
                    """elements => elements
                        .filter(element =>
                            !element.disabled
                            && element.willValidate
                            && !element.checkValidity()
                        )
                        .map(element => ({
                            field: element.dataset.cy || element.name || element.id || element.type || element.tagName,
                            message: element.validationMessage || 'valor inválido'
                        }))"""
                )
                break
            except Exception as error:
                last_error = error
                invalid = None
                if attempt < 4:
                    await asyncio.sleep(0.8)

        if invalid is None:
            raise UtelQaError(
                "utel_submit",
                "UTEL reconstruyó el formulario durante la validación previa al "
                "envío y no permitió obtener un estado estable después de 5 intentos.",
            ) from last_error

        if not invalid:
            return

        details = "; ".join(
            f"{item.get('field', 'campo')}: {item.get('message', 'valor inválido')}"
            for item in invalid[:5]
        )
        raise UtelQaError(
            "utel_fill",
            f"El formulario contiene campos inválidos antes del envío: {details}",
        )

    async def _open_inconcert(self, page: Any, config: UtelQaConfig) -> None:
        parsed = urlparse(config.inconcert_url)
        self._crm_origin = f"{parsed.scheme}://{parsed.netloc}"
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                await page.goto(config.inconcert_url, wait_until="domcontentloaded", timeout=60000)
            except Exception as error:  # InConcert puede dejar el DOM util aunque agote el timeout.
                last_error = error
            current_path = urlparse(page.url).path.rstrip("/")
            if (
                self._is_crm_route(page.url)
                or current_path == "/login"
                or await page.locator("#userId").count()
            ):
                # /login significa que InConcert sí respondió. El formulario de
                # autenticación puede renderizarse unos segundos después y debe
                # manejarlo _login_inconcert, no clasificarse como fallo de apertura.
                return
            if attempt < 2:
                await asyncio.sleep(2)
        submission_state = (
            "El formulario UTEL ya generó POST /api/forms y no se reenviará."
            if self._submission_attempted
            else "No se observó ningún envío UTEL."
        )
        raise UtelQaError(
            "inconcert_open",
            f"InConcert no respondió después de 3 intentos. {submission_state}",
        ) from last_error

    @staticmethod
    def _lead_origin_is_balanceador(config: UtelQaConfig) -> bool:
        """Indica si el Excel ordena verificar directamente en Balanceador."""

        origin = (config.lead_origin_url or "").casefold()
        return "balance" in origin or "lead-balancer" in origin

    @staticmethod
    def _is_crm_route(url: str) -> bool:
        # El parametro redirect del login NO demuestra una sesion iniciada.
        return bool(re.match(r"^/mas/(?:home|contact)(?:/|$)", urlparse(str(url)).path))

    async def _is_inconcert_login(self, page: Any) -> bool:
        return (urlparse(page.url).path.rstrip("/") == "/login"
                or await page.locator("#userId").is_visible())

    async def _recover_inconcert_session(self, page: Any) -> None:
        if self._crm_session_recoveries >= 1:
            raise UtelQaError("inconcert_login", "InConcert volvio al login despues de recuperar la sesion. "
                              "Se detuvo la consulta sin reenviar el formulario; el estado del lead no esta verificado.")
        self._crm_session_recoveries += 1
        self.logger.warning("InConcert redirigio al login. Recuperando la sesion una vez; no se reenviara el formulario UTEL.")
        await self._login_inconcert(page)

    async def _login_inconcert(self, page: Any) -> None:
        current = urlparse(page.url)
        if self._crm_origin and f"{current.scheme}://{current.netloc}" != self._crm_origin:
            raise UtelQaError("inconcert_login", "El CRM redirigio a un dominio distinto del configurado. No se introdujeron credenciales.")
        if self._is_crm_route(page.url) and not await self._is_inconcert_login(page):
            return
        username = self._inconcert_username()
        password = self._inconcert_password()
        try:
            await page.locator("#userId").wait_for(state="visible", timeout=60000)
            await page.locator("#userId").fill(username)
            await page.locator("#password").fill(password)
            await page.locator('button[type="submit"]').first.click()
            await page.wait_for_url(self._is_crm_route, timeout=60000)
            await page.locator("#userId").wait_for(state="hidden", timeout=10000)
            if not self._is_crm_route(page.url) or await self._is_inconcert_login(page):
                raise RuntimeError("La sesion no quedo establecida")
        except Exception as error:
            # No incluir excepciones de fill: pueden contener credenciales.
            raise UtelQaError(
                "inconcert_login",
                "InConcert no completo el inicio de sesion. No se pudo verificar el lead; revisar acceso al CRM.",
            ) from None

    async def _resolve_inconcert_search_input(self, page: Any) -> Any | None:
        selectors = [
            'input[placeholder="Ingrese un texto para buscar"]:visible',
            'input[placeholder="Buscar"]:visible',
            'input[placeholder*="Buscar"]:visible',
            'input[placeholder*="buscar"]:visible',
            'input[type="search"]:visible',
            'input[placeholder="Search"]:visible',
            'input[placeholder*="search"]:visible',
        ]
        for selector in selectors:
            locator = page.locator(selector).first
            if await locator.count():
                try:
                    await locator.wait_for(state="visible", timeout=3000)
                    return locator
                except Exception:
                    continue
        return None

    async def _open_contacts(self, page: Any) -> None:
        current = urlparse(page.url)
        contacts_url = f"{current.scheme}://{current.netloc}/mas/contact/people"
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                await page.goto(contacts_url, wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_function(r"""() => location.pathname.replace(/\/$/, '') === '/login'
                    || !!document.querySelector('#userId')
                    || !!Array.from(document.querySelectorAll('input[placeholder="Ingrese un texto para buscar"], input[placeholder="Buscar"], input[placeholder="Search"], input[placeholder*="buscar"], input[placeholder*="search"], input[type="search"]'))
                        .find(el => el.getClientRects().length)""", timeout=45000)
                if await self._is_inconcert_login(page):
                    await self._recover_inconcert_session(page)
                    continue
                search_input = await self._resolve_inconcert_search_input(page)
                if search_input is None:
                    raise UtelQaError("inconcert_contacts", "No se encontro el campo de busqueda en InConcert.")
                await search_input.wait_for(state="visible", timeout=45000)
                return
            except UtelQaError:
                raise
            except Exception as error:
                last_error = error
                if await self._is_inconcert_login(page):
                    await self._recover_inconcert_session(page)
                    continue
                search_input = await self._resolve_inconcert_search_input(page)
                if search_input is not None and await search_input.count() and await search_input.is_visible():
                    return
                if attempt < 2:
                    await asyncio.sleep(2)
        raise UtelQaError(
            "inconcert_contacts",
            "No se pudo abrir Contactos en InConcert despues de 3 intentos. No se pudo verificar el estado del lead.",
        ) from last_error

    async def _search_contact_with_session(self, page: Any, filter_name: str, value: str, expected_name: str) -> bool:
        for attempt in range(2):
            if await self._is_inconcert_login(page):
                await self._recover_inconcert_session(page)
                await self._open_contacts(page)
            try:
                await self._apply_contact_search(page, filter_name, value)
                found = await self._has_single_exact_name(page, expected_name)
                if not await self._is_inconcert_login(page):
                    return found
            except Exception as error:
                if not await self._is_inconcert_login(page):
                    raise
                self.logger.warning("La consulta de contactos fue interrumpida por el login.")
            await self._recover_inconcert_session(page)
            await self._open_contacts(page)
        raise UtelQaError("inconcert_search", "No se pudo completar la consulta despues de recuperar la sesion. No se reenvio el formulario.")

    async def _search_lead(self, page: Any, email: str, expected_name: str) -> None:
        # El listado no muestra Email. Filtramos por email y validamos la fila
        # mediante el nombre sintético único generado para cada ejecución.
        # InConcert puede tardar en indexar el envío. No retenemos el flujo
        # cuatro minutos: al agotarse este tiempo se consulta el Balanceador
        # como respaldo desde run(), sin reenviar el formulario.
        indexing_wait_seconds = max(15, int(self.settings.inconcert_index_wait_seconds))
        indexing_deadline = perf_counter() + indexing_wait_seconds
        attempt = 0
        email_candidates = []
        for value in (email, email.casefold()):
            normalized = self._normalize(value)
            if normalized:
                email_candidates.append(normalized)
        unique_email_candidates = list(dict.fromkeys(email_candidates))
        while True:
            attempt += 1
            # InConcert normaliza los emails al almacenarlos y su filtro puede
            # ser sensible a mayusculas/minusculas.
            for candidate in unique_email_candidates:
                if await self._search_contact_with_session(page, "Email", candidate, expected_name):
                    if attempt > 1:
                        self.logger.info(
                            "Lead %s localizado en InConcert despues de %s consultas de indexacion.",
                            expected_name,
                            attempt,
                        )
                    return

            remaining = indexing_deadline - perf_counter()
            if remaining <= 0:
                break
            self.logger.info(
                "InConcert aun no indexa %s; nuevo intento en 10 segundos (intento %s).",
                expected_name,
                attempt,
            )
            await asyncio.sleep(min(10, remaining))

        # En algunos tenants el filtro Email de la vista basica es inestable.
        # El email se vuelve a comprobar dentro de Gestionar antes de aceptar.
        # Algunos tenants concatenan un apellido vacío como un punto final.
        if await self._search_contact_with_session(page, "Nombre", f"{expected_name} .", expected_name):
            self.logger.warning(
                "El lead se localizo por el nombre unico %s; el email se verificara en Gestionar.",
                expected_name,
            )
            return
        if await self._search_contact_with_session(page, "Nombre", expected_name.rstrip(" ."), expected_name):
            self.logger.warning(
                "El lead se localizo por el nombre sin el sufijo punto %s; el email se verificara en Gestionar.",
                expected_name,
            )
            return
        raise LeadNotFoundError(
            "inconcert_search",
            f"No se encontro el lead por email ({email}) ni por nombre ({expected_name}) despues de esperar su indexacion.",
        )

    async def _search_lead_balancer(self, page: Any, email: str, expected_name: str) -> None:
        """Busca el lead en el Balanceador y conserva la URL de su detalle."""

        configured_url = self.settings.lead_balancer_url.rstrip("/") + "/"
        parsed = urlparse(configured_url)
        if parsed.scheme not in {"http", "https"} or parsed.netloc != "lead-balancer.scalahed.com":
            raise UtelQaError("lead_balancer_search", "La URL del Balanceador no es valida o no pertenece al dominio autorizado.")
        # La búsqueda siempre comienza en el listado oficial, aunque .env
        # contenga por error la URL de login u otra ruta del mismo dominio.
        base_url = f"{parsed.scheme}://{parsed.netloc}/leads/"
        response = await page.goto(base_url, wait_until="domcontentloaded", timeout=60000)
        challenge_detected = (
            (response is not None and response.status in {401, 403})
            or "__cf_chl" in page.url
        )
        challenge_resolved = not challenge_detected
        if challenge_detected:
            # En Chrome visible, Cloudflare puede completar su comprobación y
            # guardar la autorización en el perfil QA. Se espera una sola vez
            # antes de clasificar el acceso como bloqueo temporal.
            deadline = perf_counter() + 45
            while perf_counter() < deadline:
                if "__cf_chl" not in page.url and (
                    "/login" in page.url or "/leads" in page.url
                ):
                    challenge_resolved = True
                    break
                await asyncio.sleep(1)
        if not challenge_resolved:
            raise UtelQaError(
                "lead_balancer_search",
                "El Balanceador bloqueo esta sesion del navegador antes del login. "
                "Completa la verificacion visible de Cloudflare; la sesion quedara guardada en el perfil Chrome QA.",
            )
        login_path = urlparse(page.url).path.rstrip("/")
        visible_password = await self._locator_count(
            page.locator("input[type='password']:visible"),
            timeout_ms=2500,
        )
        login_required = "/login" in page.url or bool(visible_password)

        # Algunos despliegues redirigen /leads/ al home "/" antes de montar el
        # formulario de login. En ese caso abrimos directamente la ruta canónica
        # de autenticación con next=/leads/.
        if not login_required and login_path in {"", "/"}:
            canonical_login_url = (
                f"{parsed.scheme}://{parsed.netloc}/login/?next=/leads/"
            )
            try:
                await page.goto(
                    canonical_login_url,
                    wait_until="domcontentloaded",
                    timeout=60000,
                )
                login_required = True
            except Exception:
                # Si la sesión ya estaba autenticada, la fase canónica /leads/
                # de abajo volverá a intentarlo sin asumir que el login falló.
                login_required = "/login" in page.url

        if login_required:
            username = self._secret_value(self.settings.lead_balancer_username)
            password = self._secret_value(self.settings.lead_balancer_password)
            if not username or not password:
                raise UtelQaError(
                    "lead_balancer_search",
                    "La sesión guardada del Balanceador venció y no hay credenciales "
                    "configuradas para recuperarla.",
                )

            login_error: Exception | None = None
            login_completed = False
            canonical_login_url = (
                f"{parsed.scheme}://{parsed.netloc}/login/?next=/leads/"
            )

            for login_attempt in range(3):
                # Si estamos en "/" o en una pantalla intermedia sin campos,
                # reabrimos explícitamente el login oficial.
                if urlparse(page.url).path.rstrip("/") in {"", "/"}:
                    with suppress(Exception):
                        await page.goto(
                            canonical_login_url,
                            wait_until="domcontentloaded",
                            timeout=60000,
                        )

                try:
                    await page.wait_for_function(
                        r"""() => {
                            const path = location.pathname.replace(/\/$/, '');
                            if (path === '/leads') return true;
                            const password = [...document.querySelectorAll('input[type="password"]')]
                                .find(el => el.getClientRects().length);
                            return !!password;
                        }""",
                        timeout=25000,
                    )
                except Exception as error:
                    login_error = error

                if urlparse(page.url).path.rstrip("/") == "/leads":
                    login_completed = True
                    break

                username_input = page.locator(
                    "input[name='email']:visible, input[name='username']:visible, "
                    "input[name='login']:visible, input[id*='email' i]:visible, "
                    "input[id*='user' i]:visible, input[type='email']:visible, "
                    "input[autocomplete='username']:visible, input[type='text']:visible"
                ).first
                password_input = page.locator(
                    "input[type='password']:visible, "
                    "input[autocomplete='current-password']:visible"
                ).first

                if not await self._locator_count(username_input, timeout_ms=6000):
                    username_input = page.get_by_placeholder(
                        re.compile(r"correo|email|usuario|username|user|login", re.I)
                    ).first
                if not await self._locator_count(username_input, timeout_ms=6000):
                    username_input = page.get_by_label(
                        re.compile(r"correo|email|usuario|username|user|login", re.I)
                    ).first

                if (
                    await self._locator_count(username_input, timeout_ms=6000)
                    and await self._locator_count(password_input, timeout_ms=6000)
                ):
                    try:
                        await username_input.fill(username)
                        await password_input.fill(password)
                        submit = page.locator(
                            "button[type='submit']:visible, input[type='submit']:visible, "
                            "button:has-text('Ingresar'):visible, "
                            "button:has-text('Iniciar'):visible, "
                            "button:has-text('Login'):visible"
                        ).first
                        await submit.wait_for(state="visible", timeout=10000)
                        await submit.click()

                        # No exigimos que el login redirija directamente a /leads;
                        # algunos despliegues terminan primero en "/".
                        with suppress(Exception):
                            await page.wait_for_function(
                                r"""() => !location.pathname.startsWith('/login')""",
                                timeout=30000,
                            )
                        login_completed = True
                        break
                    except Exception as error:
                        login_error = error

                if login_attempt < 2:
                    with suppress(Exception):
                        await page.goto(
                            canonical_login_url,
                            wait_until="domcontentloaded",
                            timeout=60000,
                        )
                    await asyncio.sleep(3)

            if not login_completed:
                raise UtelQaError(
                    "lead_balancer_search",
                    "El Balanceador no terminó de cargar o autenticar su login "
                    "después de 3 intentos. Se reintentará únicamente la "
                    "verificación CRM; no se reenviará UTEL.",
                ) from login_error

        # La ruta canónica del Balanceador para buscar leads es /leads/.
        # Aunque una sesión válida redirija al dashboard o a la página principal,
        # nunca se intenta buscar el email desde allí: se fuerza el listado oficial.
        leads_page_ready = False
        leads_navigation_error: Exception | None = None
        for leads_attempt in range(3):
            current_path = urlparse(page.url).path.rstrip("/")
            if current_path == "/leads":
                leads_page_ready = True
                break

            try:
                await page.goto(
                    base_url,
                    wait_until="domcontentloaded",
                    timeout=60000,
                )

                if "/login" in page.url:
                    raise UtelQaError(
                        "lead_balancer_search",
                        "La sesión del Balanceador volvió al login al intentar abrir "
                        "/leads/. Reintenta únicamente la verificación CRM; no "
                        "reenvíes el formulario UTEL.",
                    )

                await page.wait_for_function(
                    r"""() => location.pathname.replace(/\/$/, '') === '/leads'""",
                    timeout=15000,
                )
                leads_page_ready = True
                break
            except UtelQaError:
                raise
            except Exception as error:
                leads_navigation_error = error
                if leads_attempt < 2:
                    await asyncio.sleep(2)

        if not leads_page_ready:
            raise UtelQaError(
                "lead_balancer_search",
                "El Balanceador mantuvo la sesión en su página principal y no "
                "permitió abrir https://lead-balancer.scalahed.com/leads/ después "
                "de 3 intentos. No se reenvió el formulario UTEL.",
            ) from leads_navigation_error

        email_input = page.get_by_label(re.compile(r"^Email$", re.I)).first
        if not await self._locator_count(email_input, timeout_ms=1500):
            email_input = page.locator(
                "label:has-text('Email')"
            ).locator("xpath=following::input[1]").first
        if not await self._locator_count(email_input, timeout_ms=1500):
            email_input = page.locator(
                "input[placeholder*='Correo electronico' i]:visible, "
                "input[placeholder*='Correo electrónico' i]:visible, "
                "input[name='email']:visible, input[type='email']:visible"
            ).first
        if not await self._locator_count(email_input, timeout_ms=1500):
            raise UtelQaError("lead_balancer_search", "No se encontro el campo Email en el Balanceador.")
        await email_input.fill(email)
        search_button = page.get_by_role("button", name=re.compile(r"^Buscar$", re.I)).first
        await search_button.click()

        deadline = perf_counter() + 90
        next_refresh = perf_counter() + 15
        matching_row = None
        # El Balanceador puede tardar varios segundos en renderizar la tabla.
        # Se observa el DOM antes de repetir la consulta para no reiniciar la
        # carga con clics continuos sobre Buscar. También se ignoran espacios
        # visuales que DataTables pudiera insertar dentro del correo.
        compact_email = re.sub(r"\s+", "", email).casefold()
        while True:
            rows = page.locator("table tbody tr:visible")
            for index in range(await rows.count()):
                row = rows.nth(index)
                compact_row_text = re.sub(r"\s+", "", await row.inner_text()).casefold()
                if compact_email in compact_row_text:
                    matching_row = row
                    break
            if matching_row is not None:
                break

            now = perf_counter()
            if now >= deadline:
                break
            if now >= next_refresh:
                await search_button.click()
                next_refresh = perf_counter() + 15
                continue
            await asyncio.sleep(min(0.5, deadline - now, next_refresh - now))
        if matching_row is None:
            raise LeadNotFoundError(
                "lead_balancer_search",
                f"No se encontro el lead por email ({email}) en el Balanceador despues de esperar su indexacion.",
            )

        # El botón verde de Acciones es un enlace, pero la ruta puede cambiar
        # entre /leads/detail/<id> y otras variantes. Se toma la primera acción
        # de la última celda en vez de exigir una ruta específica.
        detail_action = matching_row.locator(
            "td:last-child a[href]:visible, td:last-child button:visible, "
            "a.btn-success[href]:visible, button.btn-success:visible"
        ).first
        detail_page = page
        if await self._locator_count(detail_action, timeout_ms=1500):
            href = await detail_action.get_attribute("href")
            target = (await detail_action.get_attribute("target") or "").casefold()
            if href and urlparse(urljoin(base_url, href)).netloc != parsed.netloc:
                raise UtelQaError(
                    "lead_balancer_search",
                    "La accion del lead apunta fuera del dominio autorizado del Balanceador.",
                )
            if target == "_blank":
                async with page.context.expect_page() as popup_info:
                    await detail_action.click()
                detail_page = await popup_info.value
                await detail_page.wait_for_load_state("domcontentloaded", timeout=60000)
            else:
                await detail_action.click()
        else:
            detail_button = matching_row.get_by_title(re.compile(r"Ver detalle", re.I)).first
            if not await self._locator_count(detail_button, timeout_ms=1500):
                detail_button = matching_row.locator("a[href]:visible, button:visible").last
            await detail_button.click()

        # La URL de detalle no tiene un formato único; basta con comprobar que
        # salimos del listado /leads/ y permanecemos en el dominio autorizado.
        def is_detail_url(value: str) -> bool:
            current = urlparse(value)
            return current.netloc == parsed.netloc and current.path.rstrip("/") != "/leads"

        await detail_page.wait_for_url(
            is_detail_url,
            timeout=60000,
        )
        body = await detail_page.locator("body").inner_text()
        if compact_email not in re.sub(r"\s+", "", body).casefold():
            raise UtelQaError("lead_balancer_search", f"El detalle abierto en Balanceador no coincide con el email {email}.")
        self.lead_url = detail_page.url

    async def _apply_contact_search(self, page: Any, filter_name: str, value: str) -> None:
        search_input = await self._resolve_inconcert_search_input(page)
        if search_input is None:
            raise UtelQaError("inconcert_search", "No se pudo ubicar el campo de busqueda en InConcert.")
        filter_container = search_input.locator("xpath=ancestor::div[contains(@class,'input-group')][1]")
        filter_button = filter_container.locator("button.dropdown-toggle").first
        current_filter = ""
        if await self._locator_count(filter_button, timeout_ms=1200) > 0:
            try:
                # Evita esperas largas si la interfaz no muestra el filtro.
                await filter_button.wait_for(state="visible", timeout=800)
                current_filter = self._normalize(await filter_button.inner_text(timeout=1000))
            except Exception:
                current_filter = ""
            if current_filter and current_filter != self._normalize(filter_name):
                await filter_button.click(force=True)
                option = page.locator("a.dropdown-item:visible").filter(
                    has_text=re.compile(rf"^{re.escape(filter_name)}$", re.I)
                ).first
                option_normalized = self._normalize(filter_name)
                selected_filter = False
                try:
                    if await self._locator_count(option, timeout_ms=1200):
                        await option.click(force=True)
                        selected_filter = True
                    else:
                        fallback = page.locator("a.dropdown-item:visible").filter(
                            has_text=re.compile(rf"{re.escape(option_normalized)}", re.I)
                        ).first
                        if await self._locator_count(fallback, timeout_ms=1200):
                            await fallback.click(force=True)
                            selected_filter = True
                except Exception:
                    selected_filter = False
                if not selected_filter:
                    close_button = page.locator("button[title='Cerrar']").first
                    if await self._locator_count(close_button, timeout_ms=1200):
                        await close_button.click(force=True)
        if current_filter and current_filter != self._normalize(filter_name):
            # Si no logramos ajustar el filtro, se intenta el filtro actual por robustez.
            self.logger.warning("No fue posible cambiar el filtro de InConcert a %s; se usa el filtro actual.", filter_name)
        await search_input.fill(value)
        condition_container = filter_container.locator("xpath=ancestor::div[contains(@class,'flexCondition')][1]")
        search_button = condition_container.locator("button[title='Buscar']:visible").first
        if not await self._locator_count(search_button, timeout_ms=1200):
            search_button = page.locator("button[title='Buscar']:visible").first
        if not await self._locator_count(search_button, timeout_ms=1200):
            search_button = page.locator("button[type='submit']:visible").first
        try:
            async with page.expect_response(
                lambda response: "/api/contact/get_contacts/" in response.url
                and response.request.method == "POST",
                timeout=30000,
            ):
                if await self._locator_count(search_button, timeout_ms=1200):
                    await search_button.click(force=True)
                else:
                    await search_input.press("Enter")
        except Exception:
            if await self._is_inconcert_login(page):
                raise
            # Si la respuesta no es observable, la tabla sigue siendo la fuente
            # de verdad para la comprobacion posterior.
            if await self._locator_count(search_button, timeout_ms=1200):
                await search_button.click(force=True)
            else:
                await search_input.press("Enter")
        await asyncio.sleep(1)

    async def _locator_count(self, locator: Any, timeout_ms: int = 2000) -> int:
        try:
            return await asyncio.wait_for(locator.count(), timeout=timeout_ms / 1000)
        except Exception:
            return 0

    async def _has_single_exact_name(self, page: Any, expected_name: str) -> bool:
        matches = await self._matching_contact_rows(page, expected_name)
        if len(matches) > 1:
            raise UtelQaError(
                "inconcert_search",
                f"InConcert devolvio {len(matches)} contactos con el nombre {expected_name}; requiere revision manual.",
            )
        return len(matches) == 1

    async def _matching_contact_rows(self, page: Any, expected_name: str) -> list[Any]:
        expected = self._normalize(expected_name).strip(" .")
        rows = page.locator("table tbody tr:visible")
        matching_rows: list[Any] = []
        for row_index in range(await rows.count()):
            row = rows.nth(row_index)
            cells = row.locator("td")
            for cell_index in range(await cells.count()):
                cell_text = self._normalize((await cells.nth(cell_index).inner_text()).strip()).strip(" .")
                if cell_text == expected:
                    matching_rows.append(row)
                    break
        return matching_rows

    @staticmethod
    def _is_inconcert_contact_detail(url: str) -> bool:
        """Reconoce la ficha individual de un contacto de InConcert."""

        return bool(
            re.search(
                r"/mas/contact/people/view/\d+/?$",
                urlparse(str(url)).path,
                re.I,
            )
        )

    async def _visible_activity_entry(self, page: Any) -> bool:
        """Indica si la sección Actividad ya renderizó al menos un evento."""

        entries = page.get_by_text(
            re.compile(r"^(Creaci[oó]n|Conversi[oó]n)$", re.I)
        )
        for index in range(await entries.count()):
            try:
                if await entries.nth(index).is_visible():
                    return True
            except Exception:
                continue
        return False

    async def _find_activity_refresh_button(self, page: Any) -> Any | None:
        """Localiza el botón Actualizar del panel Actividad con varios fallbacks."""

        candidates = [
            page.get_by_title(re.compile(r"^(Actualizar|Recargar|Refresh)$", re.I)).first,
            page.get_by_role(
                "button",
                name=re.compile(r"^(Actualizar|Recargar|Refresh)$", re.I),
            ).first,
            page.locator(
                'button[aria-label*="actualizar" i]:visible, '
                'button[aria-label*="recargar" i]:visible, '
                'button[aria-label*="refresh" i]:visible, '
                '[role="button"][aria-label*="actualizar" i]:visible, '
                '[role="button"][aria-label*="recargar" i]:visible'
            ).first,
            page.locator(
                'button[data-original-title*="actualizar" i]:visible, '
                'button[data-bs-original-title*="actualizar" i]:visible, '
                'button[ng-reflect-ngb-tooltip*="actualizar" i]:visible, '
                'button[mattooltip*="actualizar" i]:visible, '
                '[role="button"][data-original-title*="actualizar" i]:visible'
            ).first,
            page.locator(
                'button:has(i[class*="refresh"]):visible, '
                'button:has(i[class*="sync"]):visible, '
                'button:has([class*="refresh"]):visible, '
                'button:has([class*="sync"]):visible, '
                'button:has(svg[data-icon*="rotate"]):visible, '
                'button:has(svg[data-icon*="refresh"]):visible'
            ).first,
        ]

        for candidate in candidates:
            try:
                if await self._locator_count(candidate, timeout_ms=1200):
                    await candidate.wait_for(state="visible", timeout=1500)
                    return candidate
            except Exception:
                continue

        # Último respaldo: se revisan los botones pequeños situados en la misma
        # franja horizontal del título Actividad y se confirma el tooltip al pasar
        # el cursor. Esto evita depender de una clase CSS concreta de InConcert.
        heading = page.get_by_text("Actividad", exact=True).first
        try:
            heading_box = await heading.bounding_box()
        except Exception:
            heading_box = None
        if not heading_box:
            return None

        buttons = page.locator("button:visible")
        for index in range(await buttons.count()):
            button = buttons.nth(index)
            try:
                box = await button.bounding_box()
                if not box:
                    continue
                same_header_row = (
                    abs((box["y"] + box["height"] / 2)
                        - (heading_box["y"] + heading_box["height"] / 2)) <= 70
                )
                to_the_right = box["x"] >= heading_box["x"]
                near_heading = box["x"] <= heading_box["x"] + 700
                if not (same_header_row and to_the_right and near_heading):
                    continue
                await button.hover(timeout=1000)
                tooltip = page.get_by_text(
                    re.compile(r"^(Actualizar|Recargar|Refresh)$", re.I)
                ).last
                if (
                    await self._locator_count(tooltip, timeout_ms=500)
                    and await tooltip.is_visible()
                ):
                    return button
            except Exception:
                continue
        return None

    async def _refresh_inconcert_activity(self, page: Any) -> bool:
        """Pulsa Actualizar en Actividad y espera a que el panel reaccione."""

        button = await self._find_activity_refresh_button(page)
        if button is None:
            return False
        try:
            await button.scroll_into_view_if_needed()
            await button.click(force=True, timeout=5000)
            self.logger.info(
                "La actividad de InConcert no estaba cargada; se pulsó Actualizar."
            )
            await asyncio.sleep(2)
            return True
        except Exception as error:
            self.logger.warning(
                "Se encontró el botón Actualizar, pero no fue posible pulsarlo: %s",
                error,
            )
            return False

    async def _ensure_inconcert_activity_loaded(self, page: Any) -> None:
        """Recarga el panel Actividad cuando la ficha abre sin eventos visibles."""

        await page.get_by_text("Actividad", exact=True).first.wait_for(
            state="visible",
            timeout=60000,
        )
        if await self._visible_activity_entry(page):
            return

        last_error: Exception | None = None
        for attempt in range(3):
            clicked = await self._refresh_inconcert_activity(page)
            if not clicked:
                last_error = RuntimeError(
                    "No se encontró el botón Actualizar del panel Actividad."
                )
                # La recarga completa se reserva como respaldo; primero siempre se
                # intenta el botón mostrado por InConcert.
                if attempt == 2:
                    try:
                        await page.reload(
                            wait_until="domcontentloaded",
                            timeout=60000,
                        )
                        await page.get_by_text("Actividad", exact=True).first.wait_for(
                            state="visible",
                            timeout=30000,
                        )
                    except Exception as error:
                        last_error = error
                else:
                    await asyncio.sleep(2)
            try:
                deadline = perf_counter() + 15
                while perf_counter() < deadline:
                    if await self._visible_activity_entry(page):
                        return
                    await asyncio.sleep(0.5)
            except Exception as error:
                last_error = error

        raise UtelQaError(
            "inconcert_manage",
            "La ficha del lead abrió, pero la tabla Actividad no cargó después "
            "de pulsar Actualizar tres veces.",
            'button[title="Actualizar"], button[aria-label*="Actualizar"]',
        ) from last_error

    async def _open_manage(
        self,
        page: Any,
        expected_name: str,
        expected_email: str,
    ) -> Any:
        """Abre Gestionar, incluso cuando InConcert lo lanza en otra pestaña."""

        matching_rows = await self._matching_contact_rows(page, expected_name)
        if len(matching_rows) != 1:
            raise UtelQaError(
                "inconcert_manage",
                f"No se pudo identificar una unica fila para {expected_name} antes de abrir Gestionar.",
            )

        result_row = matching_rows[0]
        menu_button = result_row.locator(
            "button.btn-only-icon:visible, button:visible"
        ).last
        await menu_button.click(force=True)
        manage = page.locator('[title="Gestionar"]:visible').first
        if not await self._locator_count(manage, timeout_ms=1500):
            manage = page.get_by_text("Gestionar", exact=True).first

        context = page.context
        pages_before = list(context.pages)
        await manage.click(force=True)

        # En varios tenants, Gestionar abre una pestaña nueva. El código anterior
        # seguía observando el listado y por eso nunca guardaba la URL /view/<id>.
        detail_page = None
        deadline = perf_counter() + 60
        while perf_counter() < deadline:
            candidates = list(context.pages)
            # Se prefieren páginas nuevas, pero también se admite navegación en
            # la misma pestaña para conservar compatibilidad entre tenants.
            ordered = [
                *[candidate for candidate in candidates if candidate not in pages_before],
                page,
            ]
            for candidate in ordered:
                try:
                    if self._is_inconcert_contact_detail(candidate.url):
                        detail_page = candidate
                        break
                except Exception:
                    continue
            if detail_page is not None:
                break
            await asyncio.sleep(0.25)

        if detail_page is None:
            raise UtelQaError(
                "inconcert_manage",
                "Se accionó Gestionar, pero InConcert no abrió la ficha individual "
                "del contacto en la pestaña actual ni en una pestaña nueva.",
                '[title="Gestionar"], text=Gestionar',
            )

        detail_page.set_default_timeout(30000)
        with suppress(Exception):
            await detail_page.wait_for_load_state(
                "domcontentloaded",
                timeout=60000,
            )
        await self._show_active_page(detail_page)

        # Se conserva el enlace apenas aparece la ruta inequívoca. Incluso si la
        # actividad tarda o falla después, BotReportService podrá escribirlo en
        # el Excel como validación pendiente.
        self.lead_url = detail_page.url

        try:
            await detail_page.wait_for_function(
                """({ expectedName, expectedEmail }) => {
                    const text = (document.body?.innerText || '').toLocaleLowerCase();
                    return text.includes(expectedName.toLocaleLowerCase())
                        && text.includes(expectedEmail.toLocaleLowerCase());
                }""",
                arg={"expectedName": expected_name, "expectedEmail": expected_email},
                timeout=60000,
            )
        except Exception as error:
            failure = UtelQaError(
                "inconcert_manage",
                f"La ficha de {expected_name} abrió y su URL fue guardada, pero "
                f"no se pudo confirmar visualmente el email {expected_email}.",
            )
            failure.url = detail_page.url
            raise failure from error

        try:
            await self._ensure_inconcert_activity_loaded(detail_page)
        except UtelQaError as error:
            error.url = detail_page.url
            raise

        body_text = await detail_page.locator("body").inner_text()
        if expected_email.casefold() not in body_text.casefold():
            failure = UtelQaError(
                "inconcert_manage",
                f"El contacto {expected_name} fue abierto, pero su email no coincide con {expected_email}.",
            )
            failure.url = detail_page.url
            raise failure

        self.lead_url = detail_page.url
        return detail_page

    async def _confirm_conversion(self, page: Any, config: UtelQaConfig) -> None:
        """Confirma Conversión y recarga Actividad cuando el timeline está vacío."""

        conversion_error: Exception | None = None
        conversion = None
        for attempt in range(4):
            conversion = page.get_by_text(
                re.compile(r"^Conversi[oó]n$", re.I)
            ).first
            try:
                await conversion.wait_for(
                    state="visible",
                    timeout=12000 if attempt else 20000,
                )
                await conversion.click()
                conversion_error = None
                break
            except Exception as error:
                conversion_error = error
                if attempt == 3:
                    break
                refreshed = await self._refresh_inconcert_activity(page)
                if not refreshed:
                    # Si el control cambió en un tenant, una recarga completa es
                    # el último respaldo. No se pierde self.lead_url.
                    try:
                        await page.reload(
                            wait_until="domcontentloaded",
                            timeout=60000,
                        )
                        await page.get_by_text("Actividad", exact=True).first.wait_for(
                            state="visible",
                            timeout=30000,
                        )
                    except Exception as reload_error:
                        conversion_error = reload_error
                await asyncio.sleep(3)

        if conversion_error is not None or conversion is None:
            failure = UtelQaError(
                "inconcert_conversion",
                "No se encontró el evento Conversión después de recargar la "
                "tabla Actividad. La URL del lead sí quedó guardada.",
                'text=/^Conversión$/i, button[title="Actualizar"]',
            )
            failure.url = self.lead_url or page.url
            raise failure from conversion_error

        if config.program_name:
            program_data = {"found": False, "text": ""}
            for _ in range(20):
                program_data = await page.evaluate(
                    """() => {
                        const normalize = (value) => String(value || '').toLowerCase().normalize('NFD').replace(/[\\u0300-\\u036f]/g, '').replace(/\\s+/g, ' ').trim();
                        const label = [...document.querySelectorAll('*')].find((node) => {
                            if (normalize(node.textContent) !== 'programadeinteres' || node.children.length !== 0) return false;
                            const style = window.getComputedStyle(node);
                            return style.display !== 'none' && style.visibility !== 'hidden' && node.getClientRects().length > 0;
                        });
                        if (!label) return { found: false, text: '' };
                        const container = label.parentElement;
                        return { found: true, text: container?.innerText || container?.textContent || '' };
                    }"""
                )
                if program_data.get("found"):
                    break
                await asyncio.sleep(1)
            expected_programs = [self._normalize(config.program_name)]
            for prefix in ("carrera en ", "licenciatura en ", "maestria en ", "doctorado en "):
                if expected_programs[0].startswith(prefix):
                    expected_programs.append(expected_programs[0][len(prefix):].strip())
            actual_program = self._normalize(program_data.get("text", ""))
            actual_program = re.sub(r"^programadeinteres\s*", "", actual_program).strip()
            program_matches = any(
                expected == actual_program
                or expected in actual_program
                or actual_program in expected
                or SequenceMatcher(None, expected, actual_program).ratio() >= 0.96
                for expected in expected_programs
                if expected and actual_program
            )
            if not program_data.get("found") or not program_matches:
                failure = UtelQaError(
                    "inconcert_program_validation",
                    f"El programa de InConcert no coincide. Excel: '{config.program_name}' | InConcert: '{actual_program or 'sin valor'}'.",
                    "ProgramaDeInteres",
                )
                failure.url = self.lead_url or page.url
                raise failure

    async def _set_dynamic_field(self, form: Any, selector: str, value: str) -> None:
        if not value:
            return
        field = form.locator(selector).first
        if not await field.count():
            return
        tag_name = await field.evaluate("(el) => el.tagName.toLowerCase()")
        if selector == '[data-cy="productsInput"]' and tag_name == "input":
            await self._select_program_autocomplete(form, field, value, selector)
            return
        if tag_name == "select":
            await field.wait_for(state="visible", timeout=12000)
            await self._wait_for_select_options(field)
            options = await field.locator("option").evaluate_all(
                "elements => elements.map(option => ({ text: option.textContent || '', value: option.value || '' }))"
            )
            wanted = [self._normalize(value)]
            # En los formularios de algunas PDP, el nivel Licenciatura se
            # representa como el área "Carrera"; no existe una option literal
            # llamada Licenciatura.
            if selector == '[data-cy="educationLevelInput"]':
                normalized_level = self._normalize(value)
                if normalized_level and not normalized_level.endswith("s"):
                    wanted.append(f"{normalized_level}s")
                if "licenciatura" in normalized_level:
                    wanted.extend(["licenciatura", "licenciaturas", "carrera", "carreras"])
                elif "maestria" in normalized_level:
                    wanted.extend(["maestria", "maestrias", "master", "masteres", "magister", "magisteres"])
                elif "doctorado" in normalized_level:
                    wanted.extend(["doctorado", "doctorados"])
                elif "diplomado" in normalized_level:
                    wanted.extend(["diplomado", "diplomados"])
                elif "bootcamp" in normalized_level:
                    wanted.extend(["bootcamp", "bootcamps"])
            if selector == '[data-cy="productsInput"]':
                normalized_program = self._normalize(value)
                # UTEL puede mostrar el programa sin el prefijo académico
                # que sí aparece en el Excel o en el H1 de la PDP.
                for prefix in ("carrera en ", "licenciatura en ", "maestria en ", "doctorado en "):
                    if normalized_program.startswith(prefix):
                        wanted.append(normalized_program[len(prefix):].strip())
                if normalized_program.startswith("carrera "):
                    wanted.append(normalized_program[len("carrera "):].strip())
            selected = next(
                (
                    option for option in options
                    if self._normalize(option["text"]) in wanted or self._normalize(option["value"]) in wanted
                ),
                None,
            )
            if selected is None:
                available = ", ".join(option["text"].strip() for option in options if option["text"].strip())
                raise UtelQaError(
                    "utel_fill",
                    f"El formulario no tiene una opcion equivalente a '{value}'. Opciones disponibles: {available}.",
                    selector,
                )
            for attempt in range(3):
                try:
                    await field.select_option(value=selected["value"])
                    await asyncio.sleep(1)
                    return
                except Exception as error:
                    if attempt == 2:
                        raise UtelQaError(
                            "utel_fill",
                            f"No se pudo seleccionar '{selected['text'].strip()}' porque el formulario cambio sus opciones.",
                            selector,
                        ) from error
                    await asyncio.sleep(0.5)
        await field.fill(value)
        await field.press("Enter")

    async def _select_program_autocomplete(self, form: Any, field: Any, value: str, selector: str) -> None:
        """Selecciona el programa exacto en los autocompletados de UTEL."""

        deadline = perf_counter() + 30
        while perf_counter() < deadline:
            placeholder = self._normalize(await field.get_attribute("placeholder") or "")
            if "cargando" not in placeholder and "loading" not in placeholder:
                break
            await asyncio.sleep(0.5)
        else:
            raise UtelQaError("utel_fill", "El campo de programa no termino de cargar.", selector)

        candidates = [value.strip()]
        normalized_program = self._normalize(value)
        for prefix in ("carrera en ", "licenciatura en ", "maestria en ", "doctorado en "):
            if normalized_program.startswith(prefix):
                # Conserva acentos y mayusculas quitando el mismo numero de
                # caracteres que ocupa el prefijo visible del H1.
                candidates.append(value.strip()[len(prefix):].strip())

        for search_value in dict.fromkeys(item for item in candidates if item):
            await field.fill(search_value)
            try:
                results = form.locator('[id^="result-"]:visible')
                await results.first.wait_for(state="visible", timeout=6000)
            except Exception:
                continue
            wanted = {self._normalize(item) for item in candidates}
            chosen = None
            for index in range(await results.count()):
                result = results.nth(index)
                result_text = self._normalize((await result.inner_text()).strip())
                if result_text in wanted:
                    chosen = result
                    break
            if chosen is None and await results.count() == 1:
                chosen = results.first
            if chosen is not None:
                # Los listados largos del formulario lateral viven dentro de
                # un contenedor con scroll. Un click fisico puede quedar
                # bloqueado por el overlay aunque la opcion sea visible; el
                # click DOM conserva el handler React sin depender del scroll.
                await chosen.evaluate("(element) => element.click()")
                await asyncio.sleep(0.8)
                current_value = self._normalize(await field.input_value())
                dropdown_closed = await form.locator('[id^="result-"]:visible').count() == 0
                if current_value in wanted and dropdown_closed:
                    self.selected_program_name = value.strip()
                    return

        raise UtelQaError(
            "utel_fill",
            f"No se pudo seleccionar en el formulario el programa de la pagina: '{value}'.",
            selector,
        )

    async def _dry_run_stop(self) -> None:
        self.logger.info("Dry run activo: no se enviara el formulario ni se abrira InConcert.")

    async def _fill_first_available(self, form: Any, selectors: list[str], value: str) -> None:
        for selector in selectors:
            locator = form.locator(selector).first
            if await locator.count():
                await locator.fill(value)
                return
        raise UtelQaError("utel_fill", f"No se encontro campo para completar el valor requerido.", ", ".join(selectors))

    async def _set_country_if_possible(self, form: Any, country: str) -> None:
        field = form.locator('[data-cy="countryCallingCode"]').first
        if not await field.count():
            return
        normalized_country = self._normalize(country)
        aliases = self.COUNTRY_OPTION_ALIASES.get(normalized_country, (normalized_country,))
        code = self.COUNTRY_CODES.get(normalized_country, "")
        tag_name = await field.evaluate("(el) => el.tagName.toLowerCase()")
        if tag_name != "select":
            raise UtelQaError(
                "utel_fill",
                f"El selector de país cambió de formato y no se puede validar de forma segura ({country}, {code}).",
                '[data-cy="countryCallingCode"]',
            )

        # Algunas variantes de la página cargan las opciones después de montar
        # el formulario. Se espera un tiempo breve para no confundir una carga
        # tardía con un país ausente.
        selected = None
        options_locator = field.locator("option")
        options_deadline = perf_counter() + 10
        while selected is None:
            options = await options_locator.evaluate_all(
                "elements => elements.map(option => ({ text: option.textContent || '', value: option.value || '' }))"
            )
            selected = next(
                (
                    option
                    for option in options
                    if any(
                        self._country_option_matches(alias, option["value"])
                        or self._country_option_matches(alias, option["text"])
                        for alias in aliases
                    )
                ),
                None,
            )
            if selected is not None or perf_counter() >= options_deadline:
                break
            await asyncio.sleep(0.25)
        if selected is None:
            raise UtelQaError(
                "utel_fill",
                f"El formulario no ofrece el país requerido: {country}.",
                '[data-cy="countryCallingCode"]',
            )

        current = self._normalize(await field.input_value())
        expected = self._normalize(selected["value"])
        if current != expected:
            if await field.is_disabled():
                raise UtelQaError(
                    "utel_fill",
                    f"El formulario fijó el país '{current}' y no permite cambiarlo a '{country}'.",
                    '[data-cy="countryCallingCode"]',
                )
            await field.select_option(value=selected["value"])
            await asyncio.sleep(0.3)

        confirmed = self._normalize(await field.input_value())
        if confirmed != expected:
            raise UtelQaError(
                "utel_fill",
                f"No se pudo confirmar el país {country} antes de enviar el formulario.",
                '[data-cy="countryCallingCode"]',
            )

    def _country_option_matches(self, alias: str, option_label: str) -> bool:
        """Compara países sin aceptar coincidencias parciales ambiguas."""

        normalized = self._normalize(option_label)
        # UTEL usa valores como ``Mexico (México)``. Aceptamos el nombre base,
        # pero no subcadenas peligrosas como ``India`` dentro de
        # ``British Indian Ocean Territory``.
        base_name = normalized.split(" (", 1)[0].strip()
        return alias == normalized or alias == base_name

    async def _check_privacy(self, form: Any) -> None:
        """Acepta consentimientos visibles sin confundir checkboxes opcionales."""

        selector = '[data-cy="checkboxGroup"] input[type="checkbox"], input[type="checkbox"]'
        last_error: Exception | None = None

        for form_attempt in range(4):
            try:
                checkboxes = form.locator(selector)
                count = await checkboxes.count()
            except Exception as error:
                last_error = error
                count = 0

            if not count:
                if form_attempt < 3:
                    await asyncio.sleep(0.75)
                    continue
                raise UtelQaError(
                    "utel_fill",
                    "No se encontró la aceptación de privacidad.",
                    selector,
                ) from last_error

            required_seen = 0
            checked_required = 0

            for index in range(count):
                # TarjetaBLC puede remontar el checkbox después de un click.
                # Se vuelve a resolver por índice en cada intento.
                metadata = None
                checkbox_id = ""
                is_required = False

                try:
                    checkbox = form.locator(selector).nth(index)
                    if not await checkbox.is_visible() or await checkbox.is_disabled():
                        continue

                    metadata = await checkbox.evaluate(
                        """element => {
                            const container = element.closest(
                                '[data-cy="checkboxGroup"], label, .chakra-checkbox, .form-control, div'
                            );
                            return {
                                id: element.id || '',
                                required: Boolean(
                                    element.required
                                    || element.getAttribute('aria-required') === 'true'
                                    || element.closest('[data-cy="checkboxGroup"]')
                                ),
                                text: (
                                    container?.innerText
                                    || container?.textContent
                                    || element.parentElement?.innerText
                                    || ''
                                ).trim()
                            };
                        }"""
                    )
                    checkbox_id = str(metadata.get("id") or "")
                    context = self._normalize(str(metadata.get("text") or ""))
                    is_required = bool(metadata.get("required")) or bool(
                        re.search(
                            r"privacidad|aviso|politica|terminos|consent|acepto|autoriz",
                            context,
                            re.I,
                        )
                    )
                    if is_required:
                        required_seen += 1
                except Exception as error:
                    last_error = error
                    continue

                success = False
                for click_attempt in range(3):
                    try:
                        checkbox = form.locator(selector).nth(index)
                        if await checkbox.is_checked():
                            success = True
                            break

                        # Primera opción: interacción nativa de Playwright.
                        try:
                            await checkbox.check(force=True, timeout=5000)
                        except Exception:
                            pass

                        await asyncio.sleep(0.2)
                        checkbox = form.locator(selector).nth(index)
                        if await checkbox.is_checked():
                            success = True
                            break

                        # Algunos diseños esconden el input y enlazan el evento
                        # React al <label>.
                        if checkbox_id:
                            label = form.locator(
                                f'label[for="{checkbox_id}"]:visible'
                            ).first
                            if await label.count():
                                await label.click(force=True, timeout=5000)
                        else:
                            label = checkbox.locator("xpath=ancestor::label[1]")
                            if await label.count():
                                await label.click(force=True, timeout=5000)

                        await asyncio.sleep(0.25)
                        checkbox = form.locator(selector).nth(index)
                        if await checkbox.is_checked():
                            success = True
                            break

                        # Último intento: click DOM sobre el input actual.
                        await checkbox.evaluate("(element) => element.click()")
                        await asyncio.sleep(0.25)
                        checkbox = form.locator(selector).nth(index)
                        if await checkbox.is_checked():
                            success = True
                            break
                    except Exception as error:
                        last_error = error
                        if click_attempt < 2:
                            await asyncio.sleep(0.4)

                if success:
                    if is_required:
                        checked_required += 1
                    continue

                # Un checkbox opcional que el sitio no permite activar no debe
                # bloquear el envío. Un consentimiento requerido sí.
                if is_required:
                    last_error = UtelQaError(
                        "utel_fill",
                        "No se pudo aceptar un consentimiento de privacidad requerido "
                        "después de 3 intentos.",
                        selector,
                    )
                    break

            if required_seen and checked_required == required_seen:
                return

            # Si no pudimos identificar required explícitos, al menos uno de los
            # checkboxes visibles debe haber quedado marcado.
            if not required_seen:
                try:
                    checked_visible = await form.locator(
                        f"{selector}:checked"
                    ).count()
                except Exception:
                    checked_visible = 0
                if checked_visible:
                    return

            if form_attempt < 3:
                await asyncio.sleep(0.8)
                continue

        if isinstance(last_error, UtelQaError):
            raise last_error
        raise UtelQaError(
            "utel_fill",
            "No se pudo confirmar la aceptación de privacidad después de varios intentos.",
            selector,
        ) from last_error

    async def _first_visible_program_link(self, page: Any, menu_option: Any | None = None) -> Any | None:
        if menu_option is not None:
            option_text = self._normalize((await menu_option.inner_text()).strip())
            option_box = await menu_option.bounding_box()
            menu_item = menu_option.locator("xpath=ancestor::li[1]")
            if await menu_item.count():
                nested_links = menu_item.locator("a[href]")
                for index in range(await nested_links.count()):
                    candidate = nested_links.nth(index)
                    if await candidate.is_visible():
                        text = (await candidate.inner_text()).strip()
                        candidate_box = await candidate.bounding_box()
                        is_adjacent_submenu = (
                            not option_box
                            or not candidate_box
                            or (
                                candidate_box["x"] > option_box["x"] + 20
                                and candidate_box["y"] >= option_box["y"] - 40
                                and candidate_box["y"] <= option_box["y"] + 650
                            )
                        )
                        if (
                            text
                            and self._normalize(text) != option_text
                            and is_adjacent_submenu
                            and await self._is_safe_program_link(candidate, page)
                        ):
                            return candidate
            # Los mega menus nuevos no siempre usan <li>. En ese caso, el
            # submenu de programas se identifica por su posicion a la derecha
            # del nivel que acabamos de desplegar.
            if option_box:
                visible_links = page.locator("a[href]:visible")
                for index in range(await visible_links.count()):
                    candidate = visible_links.nth(index)
                    text = (await candidate.inner_text()).strip()
                    candidate_box = await candidate.bounding_box()
                    if (
                        text
                        and candidate_box
                        and self._normalize(text) != option_text
                        and candidate_box["x"] > option_box["x"] + 20
                        and candidate_box["y"] >= option_box["y"] - 40
                        and candidate_box["y"] <= option_box["y"] + 650
                        and not re.search(r"ver todos los programas", text, re.I)
                        and await self._is_safe_program_link(candidate, page)
                    ):
                        return candidate
        links = page.locator('a[href*="licenciatura"], a[href*="maestr"], a[href*="doctor"], a[href*="program"]')
        for index in range(await links.count()):
            candidate = links.nth(index)
            if await candidate.is_visible():
                text = (await candidate.inner_text()).strip()
                if (
                    text
                    and not re.search(r"modalidad|oferta|aspirantes|becas|^licenciaturas?$|^maestr[ií]as?$|^doctorados?$|ver todos", text, re.I)
                    and await self._is_safe_program_link(candidate, page)
                ):
                    return candidate
        return None

    async def _is_safe_program_link(self, candidate: Any, page: Any) -> bool:
        """Impide que la navegacion academica abra telefono, WhatsApp u otros accesos globales."""

        href = (await candidate.get_attribute("href") or "").strip()
        text = (await candidate.inner_text()).strip()
        normalized_href = href.casefold()
        normalized_text = self._normalize(text)
        if not href or normalized_href.startswith(("tel:", "mailto:", "javascript:")):
            return False
        if any(token in normalized_href for token in ("whatsapp", "wa.me", "api.whatsapp", "campus")):
            return False
        if re.search(r"inscripciones|estudiantes|campus virtual|solicitar informacion|contacto", normalized_text, re.I):
            return False
        destination = urlparse(href)
        current = urlparse(page.url)
        if destination.netloc and current.netloc and destination.netloc.casefold() != current.netloc.casefold():
            return False
        return True

    async def _text_locator(self, page: Any, candidates: list[str]) -> Any:
        pattern = "|".join(re.escape(candidate.strip()) for candidate in candidates if candidate.strip())
        if not pattern:
            raise UtelQaError("utel_navigation", "La opcion solicitada esta vacia.")
        matches = page.get_by_text(re.compile(rf"^({pattern})s?$", re.I))
        for index in range(await matches.count()):
            candidate = matches.nth(index)
            if await candidate.is_visible():
                return candidate
        # Respaldo tolerante a acentos mal codificados en el Excel o en el DOM.
        normalized_candidates = {self._normalize(item) for item in candidates if item.strip()}
        elements = page.locator("a:visible, button:visible, [role='menuitem']:visible")
        for index in range(await elements.count()):
            candidate = elements.nth(index)
            text = self._normalize((await candidate.inner_text()).strip())
            if text in normalized_candidates or text.rstrip("s") in {item.rstrip("s") for item in normalized_candidates}:
                return candidate
        raise UtelQaError(
            "utel_navigation",
            f"No se encontro una opcion visible entre: {', '.join(candidates)}.",
            f"text=/{pattern}/i",
        )

    def _level_candidates(self, level: str) -> list[str]:
        candidates = self._spanish_variants(level)
        if not level.lower().endswith("s"):
            candidates.append(f"{level}s")
        normalized = self._normalize(level)
        if "licenciatura" in normalized:
            candidates.extend(["Licenciaturas", "Carrera", "Carreras"])
        elif "maestr" in normalized:
            candidates.extend(["Maestrias", "Maestr\u00edas", "Magister", "Magisteres", "Mag\u00edster", "Mag\u00edsteres"])
        return candidates

    def _menu_candidates(self, value: str) -> list[str]:
        candidates = self._spanish_variants(value)
        normalized = self._normalize(value)
        if "diplomado" in normalized:
            candidates.extend(["Diplomados", "Diplomados presenciales"])
        if "masteres internacionales" in normalized:
            candidates.extend(["MÃ¡steres Internacionales", "Masteres Internacionales"])
        if normalized == "maestrias":
            candidates.extend(["MaestrÃ­as", "Maestrias"])
        if normalized == "licenciaturas":
            candidates.extend(["Licenciaturas", "Carrera", "Carreras"])
        if normalized == "maestrias":
            candidates.extend(["Maestrias", "Maestr\u00edas", "Magisteres", "Mag\u00edsteres"])
        if normalized == "modalidad en linea":
            candidates.extend(["Modalidad en lÃ­nea", "Modalidad en linea"])
        if normalized == "modalidad hibrida":
            candidates.extend(["Modalidad hÃ­brida", "Modalidad hibrida"])
        return list(dict.fromkeys(candidates))

    def _education_level_candidates(self, value: str) -> list[str]:
        """Equivalencias de nivel usadas por los portales con Oferta educativa."""

        candidates = self._menu_candidates(value)
        normalized = self._normalize(value)
        if "licenciatura" in normalized or normalized in {"carrera", "carreras"}:
            candidates.extend(["Licenciatura", "Licenciaturas", "Carrera", "Carreras"])
        elif "maestr" in normalized or "magister" in normalized:
            candidates.extend(["Maestria", "Maestrias", "Maestr\u00eda", "Maestr\u00edas", "Magister", "Magisteres", "Mag\u00edster", "Mag\u00edsteres"])
        elif "doctor" in normalized:
            candidates.extend(["Doctorado", "Doctorados"])
        return list(dict.fromkeys(candidates))

    @staticmethod
    def _spanish_variants(value: str) -> list[str]:
        """Genera variantes comunes con y sin acento para textos visibles."""

        variants = {value.strip()}
        replacements = {
            "linea": "línea",
            "Linea": "Línea",
            "maestria": "maestría",
            "Maestria": "Maestría",
            "hibrida": "híbrida",
            "Hibrida": "Híbrida",
        }
        replacements.update({
            "linea": "l\u00ednea",
            "Linea": "L\u00ednea",
            "maestria": "maestr\u00eda",
            "Maestria": "Maestr\u00eda",
            "hibrida": "h\u00edbrida",
            "Hibrida": "H\u00edbrida",
            "educacion": "educaci\u00f3n",
            "Educacion": "Educaci\u00f3n",
            "titulacion": "titulaci\u00f3n",
            "Titulacion": "Titulaci\u00f3n",
            "ingles": "ingl\u00e9s",
            "Ingles": "Ingl\u00e9s",
        })
        for source, target in replacements.items():
            if source in value:
                variants.add(value.replace(source, target).strip())
        return [variant for variant in variants if variant]

    def _validate_config(self, config: UtelQaConfig) -> None:
        urls = {"utel_url": config.utel_url}
        if not config.dry_run:
            urls["inconcert_url"] = config.inconcert_url
        for field_name, value in urls.items():
            parsed = urlparse(value)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise UtelQaError("config", f"La URL {field_name} no es valida.")
        if config.form_type not in self.FORM_IDS:
            raise UtelQaError("config", "El tipo de formulario debe ser lateral, tarjeta o footer.")
        if config.program_selection_strategy == "exact_match" and not config.program_name:
            raise UtelQaError("config", "Debes indicar el nombre del programa cuando la estrategia es exact_match.")
        if (
            not config.dry_run
            and not config.defer_crm_verification
            and not self._lead_origin_is_balanceador(config)
            and not self.has_inconcert_credentials()
        ):
            raise UtelQaError(
                "config",
                "Faltan credenciales de InConcert. Configura INCONCERT_USERNAME/INCONCERT_PASSWORD o CRM_USERNAME/CRM_PASSWORD en .env.",
            )
        success_pattern = config.submit_success_pattern.strip()
        error_pattern = config.submit_error_pattern.strip() or "error|invalido|inválido|obligatorio|requerido|fall"
        # Estos patrones se usan después del clic. Validarlos aquí garantiza
        # que una expresión mal escrita falle antes de cualquier envío real.
        for label, pattern in (("éxito", success_pattern), ("error", error_pattern)):
            if not pattern:
                continue
            try:
                re.compile(pattern, re.I)
            except re.error as error:
                raise UtelQaError(
                    "config",
                    f"El patrón de {label} para confirmar el envío no es una expresión regular válida: {error}.",
                ) from error
        self._last_submit_success_pattern = success_pattern
        self._last_submit_error_pattern = error_pattern

    def _raise_if_stop_requested(
        self,
        should_stop: Callable[[], bool] | None,
    ) -> None:
        """Detiene el flujo y deja claro si el POST ya había sido observado."""

        if should_stop is None or not should_stop():
            return

        self._cancelled = True
        self._cancelled_before_submit = not self._submission_attempted
        if self._submission_attempted:
            raise UtelRunCancelled(
                "La ejecución se detuvo después de observar POST /api/forms. "
                "No se reenviará el formulario; verifica el correo generado en "
                "InConcert o Balanceador antes de reintentar."
            )
        raise UtelRunCancelled(
            "La ejecución se detuvo antes de observar POST /api/forms; "
            "el lead no se considera enviado."
        )

    async def _hover_center(self, locator: Any, page: Any) -> None:
        await locator.wait_for(state="visible")
        box = await locator.bounding_box()
        if box:
            await page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        else:
            await locator.hover()

    def _append_failed_stage(self, number: int, error: UtelQaError, url: str | None, screenshot: str | None) -> None:
        if error.stage == "utel_submit":
            self.status_flags["utel_submission"] = "failed"
            self.status_flags["utel_submission_message"] = str(error)
        if error.stage == "inconcert_login":
            self.status_flags["inconcert_login"] = "failed"
        if error.stage == "inconcert_search":
            self.status_flags["lead_found"] = "failed"
        if error.stage == "inconcert_conversion":
            self.status_flags["conversion_found"] = "failed"
        self.stage_results.append(
            UtelQaStageResult(
                step_number=number,
                stage=error.stage,
                status="FAIL",
                message=str(error),
                selector=error.selector,
                url=url,
                screenshot=screenshot,
            )
        )

    async def _safe_screenshot(self, page: Any, name: str | None) -> str | None:
        if not name or self.evidence_directory is None:
            return None
        try:
            file_path = self.evidence_directory / f"{name}.png"
            try:
                await page.screenshot(path=str(file_path), full_page=True, animations="disabled", timeout=15000)
            except Exception:
                # Una captura completa puede fallar en páginas largas; todavía
                # conservamos evidencia visible sin retrasar toda la fila.
                try:
                    await page.screenshot(path=str(file_path), full_page=False, animations="disabled", timeout=12000)
                except Exception:
                    # Algunas PDP se bloquean al desactivar animaciones. El
                    # último intento captura el viewport sin tocar su estado.
                    await page.screenshot(path=str(file_path), full_page=False, timeout=12000)
            relative = file_path.relative_to(self.settings.storage_dir.parent).as_posix()
            self.screenshots.append(relative)
            return relative
        except Exception:
            self.logger.exception("No se pudo guardar screenshot %s", name)
            return None

    def _evidence_directory(self, name: str) -> Path:
        now = datetime.now()
        unique_suffix = secrets.token_hex(3)
        directory = self.settings.storage_dir / "screenshots" / "utel_inconcert" / now.date().isoformat() / f"{self._slug(name)}_{now.strftime('%H%M%S_%f')}_{unique_suffix}"
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    @staticmethod
    def _secret_value(value: str | SecretStr) -> str:
        if isinstance(value, SecretStr):
            return value.get_secret_value().strip()
        return str(value or "").strip()

    def _inconcert_username(self) -> str:
        return self._secret_value(getattr(self.settings, "inconcert_username", "")) or self._secret_value(self.settings.crm_username)

    def _inconcert_password(self) -> str:
        return self._secret_value(getattr(self.settings, "inconcert_password", "")) or self._secret_value(self.settings.crm_password)

    def has_inconcert_credentials(self) -> bool:
        """Indica si un envío real podrá reconciliarse después contra CRM."""

        return bool(self._inconcert_username() and self._inconcert_password())

    @staticmethod
    def _normalize(value: str) -> str:
        normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii").lower()
        return re.sub(r"\s+", " ", normalized).strip()

    @staticmethod
    def _slug(value: str) -> str:
        normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
        return re.sub(r"[^a-zA-Z0-9_-]+", "-", normalized).strip("-").lower() or "utel-inconcert"

    @staticmethod
    def _friendly_error(error: Exception) -> str:
        message = str(error).strip()
        # El panel de diagnóstico permite copiar/descargar el detalle técnico.
        # Conservamos el call log completo de Playwright para poder reproducirlo.
        return message[:8000] if message else "Ocurrio un error durante la automatizacion."
