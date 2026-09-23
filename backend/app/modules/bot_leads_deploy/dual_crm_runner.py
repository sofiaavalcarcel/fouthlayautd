"""Verificación dual de leads exclusiva para Bot Leads Deploy.

La columna ``Url Origen Lead`` se usa como destino preferido, no como destino
único. Si el lead no puede confirmarse allí después de un envío real, el módulo
consulta el otro CRM sin volver a enviar el formulario de UTEL.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from time import perf_counter
from typing import Any, Callable
from urllib.parse import urlparse

from ...schemas.bot import UtelQaConfig
from .runner import (
    RejectedSubmission,
    UnconfirmedSubmission,
    UtelInconcertRunner,
    UtelQaError,
)
from .service import LeadsDeploySpreadsheetService


class LeadsDeployDualCrmRunner(UtelInconcertRunner):
    """Busca el lead en InConcert y Balanceador de forma segura y en paralelo."""

    def _can_retry_footer_submit(self, error: UtelQaError) -> bool:
        """Autoriza un segundo mecanismo solo si NO hubo ningún envío observado.

        Diplomados y Bootcamps usan FooterBLC. En algunas PDP el click visual del
        botón no dispara el ``submit`` de React, aunque todos los campos se vean
        completos. Solo reintentamos cuando el runner base confirmó que no salió
        ningún POST; así el segundo intento no puede duplicar un lead.
        """

        config = getattr(self, "_rotation_config", None)
        if config is None or getattr(config, "form_type", "") != "footer":
            return False
        if self._submission_attempted or error.stage != "utel_submit":
            return False

        message = str(error).casefold()
        return (
            "no se observó ninguna solicitud post desde la página" in message
            or "no se pudo completar el clic y no se observó post /api/forms" in message
        )

    async def _retry_footer_submit_with_request_submit(
        self,
        page: Any,
        form: Any,
        should_stop: Callable[[], bool] | None = None,
    ) -> None:
        """Dispara el submit nativo del FooterBLC y vuelve a exigir POST /api/forms.

        ``HTMLFormElement.requestSubmit`` ejecuta las validaciones del navegador y
        el ``onSubmit`` de React. No se usa ``form.submit()`` porque ese método
        saltaría handlers y validaciones del formulario.
        """

        submit_selector = 'button[type="submit"], input[type="submit"]'
        form, submit = await self._stable_utel_submit_context(
            page,
            form,
            submit_selector,
        )
        self._raise_if_stop_requested(should_stop)
        await self._show_active_page(page)
        await asyncio.sleep(0.25)

        loop = asyncio.get_running_loop()
        api_request = loop.create_future()
        api_response = loop.create_future()
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
                if is_utel_form_request(response.request) and not api_response.done():
                    api_response.set_result(response)
            except Exception:
                return

        listeners_installed = False
        try:
            page.on("request", capture_request)
            page.on("response", capture_response)
            listeners_installed = True

            await submit.scroll_into_view_if_needed()
            mechanism = await submit.evaluate(
                """button => {
                    const owner = button.form || button.closest('form');
                    if (owner && typeof owner.requestSubmit === 'function') {
                        owner.requestSubmit(button);
                        return 'requestSubmit';
                    }
                    button.click();
                    return 'button.click';
                }"""
            )
            self.logger.info(
                "FooterBLC: segundo intento seguro de envío usando %s.",
                mechanism,
            )

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
                    raise UtelQaError(
                        "utel_submit",
                        "FooterBLC recibió un segundo intento de envío, pero UTEL "
                        "siguió sin generar POST /api/forms. El lead no se considera "
                        "enviado y no se buscará en InConcert ni Balanceador."
                        f"{observed}",
                        submit_selector,
                    )
                await asyncio.sleep(min(0.25, remaining))

            api_request.result()
            self._submission_attempted = True

            response_deadline = perf_counter() + 65
            while not api_response.done():
                self._raise_if_stop_requested(should_stop)
                remaining = response_deadline - perf_counter()
                if remaining <= 0:
                    raise UnconfirmedSubmission(
                        "utel_submit",
                        "FooterBLC generó POST /api/forms, pero UTEL no entregó "
                        "una respuesta concluyente. Se verificará CRM sin reenviar.",
                        submit_selector,
                    )
                await asyncio.sleep(min(0.25, remaining))

            await self._classify_utel_api_response(api_response.result())
        finally:
            if not api_request.done():
                api_request.cancel()
            if not api_response.done():
                api_response.cancel()
            if listeners_installed:
                with suppress(Exception):
                    page.remove_listener("request", capture_request)
                    page.remove_listener("response", capture_response)

    async def _submit_utel_form(
        self,
        page: Any,
        form: Any,
        should_stop: Callable[[], bool] | None = None,
    ) -> None:
        """Envía de forma segura y evita CRM cuando UTEL confirma un rechazo.

        El primer intento conserva exactamente el runner estable. Si FooterBLC
        no emite ningún POST (caso observado en Diplomados/Bootcamps), se hace un
        único segundo intento mediante ``requestSubmit``. Nunca se reintenta si
        ya se observó un POST.
        """

        try:
            try:
                await super()._submit_utel_form(page, form, should_stop)
                return
            except RejectedSubmission:
                raise
            except UtelQaError as error:
                if not self._can_retry_footer_submit(error):
                    raise
                self.logger.warning(
                    "FooterBLC no emitió POST tras el click; se usará un segundo "
                    "mecanismo seguro antes de declarar fallo de envío."
                )
                await self._retry_footer_submit_with_request_submit(
                    page,
                    form,
                    should_stop,
                )
                return
        except RejectedSubmission as error:
            raise UtelQaError(
                "utel_submit",
                (
                    f"{error} UTEL confirmó que el formulario no fue aceptado; "
                    "Leads Deploy no consultará InConcert ni Balanceador para este caso."
                ),
                error.selector,
            ) from error

    @staticmethod
    def _failed_stage_name(result: dict[str, Any]) -> str:
        for stage in result.get("stages", []):
            if isinstance(stage, dict):
                status = stage.get("status")
                name = stage.get("stage")
            else:
                status = getattr(stage, "status", None)
                name = getattr(stage, "stage", None)
            if status == "FAIL":
                return str(name or "")
        return ""

    def _secondary_verification_config(
        self,
        config: UtelQaConfig,
        primary_result: dict[str, Any],
    ) -> UtelQaConfig | None:
        """Construye una segunda consulta CRM sin permitir un nuevo envío UTEL."""

        if primary_result.get("lead_url"):
            return None
        if primary_result.get("status") != "FAIL":
            return None

        # Nunca iniciar una búsqueda CRM si la etapa que falló fue el envío.
        # Esto cubre rechazos explícitos de UTEL y evita buscar leads inexistentes.
        failed_stage = self._failed_stage_name(primary_result)
        if failed_stage == "utel_submit":
            return None

        # Solo se permite buscar en el segundo CRM si el formulario ya fue
        # enviado, o si esta ejecución ya era una conciliación verification_only.
        if not config.verification_only and primary_result.get("utel_submission_attempted") is not True:
            return None

        origin_is_balanceador = self._lead_origin_is_balanceador(config)

        if origin_is_balanceador:
            if failed_stage and not failed_stage.startswith("lead_balancer_"):
                return None
            inconcert_url = LeadsDeploySpreadsheetService.default_inconcert_url(
                config.country
            )
            if not inconcert_url:
                self.logger.warning(
                    "Leads Deploy no tiene URL InConcert configurada para %s; "
                    "no se puede ejecutar la verificación secundaria.",
                    config.country,
                )
                return None
            return config.model_copy(
                update={
                    "verification_only": True,
                    "defer_crm_verification": False,
                    # Vaciar el origen hace que el runner base intente InConcert.
                    "lead_origin_url": "",
                    "inconcert_url": inconcert_url,
                    "keep_browser_open": False,
                }
            )

        # Si InConcert no pudo completar la verificación, intentar Balanceador.
        # El runner base ya hace InConcert -> Balanceador cuando el fallo es
        # inconcert_search; esta rama cubre también open/login/contacts.
        if failed_stage and not failed_stage.startswith("inconcert_"):
            return None
        balancer_url = str(self.settings.lead_balancer_url or "").strip()
        if not balancer_url:
            return None
        return config.model_copy(
            update={
                "verification_only": True,
                "defer_crm_verification": False,
                "lead_origin_url": balancer_url,
                "inconcert_url": balancer_url,
                # Balanceador puede presentar Cloudflare; mantener Chrome visible
                # conserva el perfil QA que ya usa este módulo.
                "browser": "chrome",
                "headless": False,
                "keep_browser_open": False,
            }
        )

    @staticmethod
    def _merge_dual_results(
        original_config: UtelQaConfig,
        primary: dict[str, Any],
        secondary: dict[str, Any],
    ) -> dict[str, Any]:
        """Une evidencia de ambos CRM sin perder el estado del envío original."""

        merged = {**primary, **secondary}
        merged["stages"] = [
            *primary.get("stages", []),
            *secondary.get("stages", []),
        ]
        merged["screenshots"] = list(
            dict.fromkeys(
                [
                    *primary.get("screenshots", []),
                    *secondary.get("screenshots", []),
                ]
            )
        )
        merged["selected_program_name"] = (
            primary.get("selected_program_name")
            or secondary.get("selected_program_name")
            or ""
        )
        merged["program_selection_notice"] = (
            primary.get("program_selection_notice")
            or secondary.get("program_selection_notice")
            or ""
        )
        merged["utel_submission_attempted"] = primary.get(
            "utel_submission_attempted",
            False,
        )

        secondary_confirmed = (
            secondary.get("status") == "PASS"
            and secondary.get("lead_found") == "success"
            and bool(secondary.get("lead_url"))
        )

        if secondary_confirmed:
            source = str(secondary.get("lead_source") or "CRM")
            merged["status"] = "PASS"
            merged["lead_found"] = "success"
            merged["lead_source"] = source
            merged["lead_url"] = secondary.get("lead_url")
            merged["summary"] = (
                f"Lead localizado en {source} después de consultar el destino "
                "alterno de Leads Deploy."
            )
            if original_config.verification_only:
                merged["utel_submission"] = primary.get(
                    "utel_submission",
                    "skipped",
                )
                merged["utel_submission_message"] = primary.get(
                    "utel_submission_message",
                    "Envío ya realizado; verificación CRM completada.",
                )
            else:
                merged["utel_submission"] = "success"
                merged["utel_submission_message"] = (
                    f"Lead confirmado en {source} sin reenviar el formulario."
                )
            return merged

        # Ningún segundo intento puede provocar un reenvío. Se conserva el
        # estado de envío del primer resultado y se reportan ambas evidencias.
        merged["status"] = "FAIL"
        merged["utel_submission"] = primary.get(
            "utel_submission",
            merged.get("utel_submission", "pending"),
        )
        merged["utel_submission_message"] = primary.get(
            "utel_submission_message",
            merged.get("utel_submission_message", ""),
        )
        merged["summary"] = (
            "No se pudo confirmar el lead después de consultar InConcert y "
            "Balanceador. El formulario no se reenvió."
        )
        return merged

    async def run(
        self,
        config: UtelQaConfig,
        should_stop: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        """Usa Url Origen Lead como prioridad y el otro CRM como respaldo."""

        primary = await super().run(config, should_stop)
        if config.parallel_crm_search:
            # Form Validation ya consultó ambos CRM en paralelo; no se debe
            # repetir una segunda búsqueda secuencial si ninguno confirmó.
            return primary
        secondary_config = self._secondary_verification_config(config, primary)
        if secondary_config is None:
            return primary

        preferred = (
            "Balanceador"
            if self._lead_origin_is_balanceador(config)
            else "InConcert"
        )
        alternate = "InConcert" if preferred == "Balanceador" else "Balanceador"
        self.logger.warning(
            "Lead no confirmado en %s; Leads Deploy consultará también %s sin reenviar UTEL.",
            preferred,
            alternate,
        )

        secondary = await super().run(secondary_config, should_stop)
        return self._merge_dual_results(config, primary, secondary)
