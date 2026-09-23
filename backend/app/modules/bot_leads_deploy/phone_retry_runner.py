"""Reintento de teléfono exclusivo de Bot Leads Deploy.

Cuando UTEL confirma un rechazo explícito del formulario (por ejemplo el toast
"Error al enviar / Contacta a soporte"), este adaptador marca el resultado para
que el batch existente reserve otro lead de prueba y pruebe con un teléfono
diferente. También estabiliza FooterBLC y mantiene visible el feedback de UTEL
sin mover la página. No cambia la lógica de otros módulos.
"""

from __future__ import annotations

import asyncio
import re
from contextlib import suppress
from typing import Any, Callable

from ...schemas.bot import UtelQaConfig
from .dual_crm_runner import LeadsDeployDualCrmRunner
from .runner import UtelQaError


class LeadsDeployPhoneRetryRunner(LeadsDeployDualCrmRunner):
    """Convierte rechazos explícitos de UTEL en candidatos a otro teléfono."""

    async def _maximize_visible_browser(self, page: Any) -> None:
        """Maximiza Chrome antes de cargar UTEL, nunca después de llenar el form."""

        try:
            session = await page.context.new_cdp_session(page)
            window = await session.send("Browser.getWindowForTarget")
            window_id = window.get("windowId")
            if window_id is not None:
                await session.send(
                    "Browser.setWindowBounds",
                    {
                        "windowId": window_id,
                        "bounds": {"windowState": "maximized"},
                    },
                )
                await asyncio.sleep(0.35)
            await session.detach()
        except Exception:
            return

    async def _open_utel(self, page: Any, config: UtelQaConfig) -> None:
        """Fija el tamaño de Chrome antes de que React monte los formularios."""

        await self._maximize_visible_browser(page)
        await super()._open_utel(page, config)

    @staticmethod
    def _program_key(value: str) -> str:
        normalized = str(value or "").lower()
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return re.sub(
            r"^(?:licenciatura|carrera|maestr[ií]a|doctorado|diplomado|bootcamp)\s+en\s+",
            "",
            normalized,
        ).strip()

    async def _stabilize_footer_before_submit(
        self,
        page: Any,
        config: UtelQaConfig,
    ) -> None:
        """Confirma que FooterBLC conserva programa, datos y privacidad juntos.

        Algunas PDP remontan FooterBLC al cambiar programa o consentimiento. El
        formulario puede verse lleno y, unos milisegundos después, perder el
        programa. Se revalida el formulario actual hasta que todos los campos
        requeridos permanezcan estables en el mismo montaje de React.
        """

        expected_program = self._selected_direct_page_program or config.program_name
        program_selector = '[data-cy="productsInput"]'

        for attempt in range(4):
            footer = self._footer_locator(page)
            await footer.wait_for(state="visible", timeout=8000)

            await self._apply_deploy_modality(footer, config)
            await self._complete_footer_academic_fields(page, footer, config)
            await self._fill_first_available(
                footer,
                ['[data-cy="textfieldInput"]', '#first_name', 'input[name="first_name"]'],
                config.lead.name,
            )
            await self._fill_first_available(
                footer,
                ['[data-cy="emailInput"]', '#email', 'input[type="email"]', 'input[name="email"]'],
                config.lead.email,
            )
            await self._set_country_if_possible(footer, config.country)
            await self._fill_first_available(
                footer,
                ['[data-cy="telephoneInput"]', '#phone', 'input[type="tel"]', 'input[name="phone"]'],
                config.lead.phone,
            )
            await self._check_privacy(footer)
            await asyncio.sleep(0.6)

            footer = self._footer_locator(page)
            await footer.wait_for(state="visible", timeout=5000)
            program_field = footer.locator(program_selector).first
            if not await program_field.count():
                raise UtelQaError(
                    "utel_fill",
                    "FooterBLC perdió el selector de programa después de llenarse.",
                    program_selector,
                )

            current_program = await program_field.evaluate(
                "element => element.tagName === 'SELECT' "
                "? element.selectedOptions[0]?.textContent || '' "
                ": element.value || ''"
            )
            program_ok = (
                bool(expected_program)
                and self._program_key(current_program)
                == self._program_key(expected_program)
            )
            checked_privacy = await footer.locator(
                'input[type="checkbox"]:checked'
            ).count()

            try:
                await self._validate_utel_form_before_submit(footer)
                html_valid = True
            except UtelQaError:
                html_valid = False

            if program_ok and checked_privacy and html_valid:
                self.selected_program_name = expected_program
                return

            self.logger.warning(
                "FooterBLC cambió después del llenado; estabilización %s/4 "
                "(programa=%s, privacidad=%s, html=%s).",
                attempt + 1,
                program_ok,
                bool(checked_privacy),
                html_valid,
            )
            if attempt < 3:
                await asyncio.sleep(0.8)

        raise UtelQaError(
            "utel_fill",
            "FooterBLC no logró conservar programa, datos personales y privacidad "
            "al mismo tiempo. No se enviará un formulario incompleto.",
            program_selector,
        )

    async def _first_existing_footer_field(
        self,
        footer: Any,
        selectors: list[str],
    ) -> Any | None:
        for selector in selectors:
            field = footer.locator(selector).first
            if await field.count() and await field.is_visible():
                return field
        return None

    async def _settle_footer_contact_state(
        self,
        page: Any,
        config: UtelQaConfig,
    ) -> None:
        """Imita el cierre natural de campos antes del clic manual.

        En las PDP de Diplomados/Bootcamps el DOM puede mostrar el teléfono y el
        programa correctos mientras React todavía conserva una validación interna
        pendiente. Un envío manual funciona con los mismos datos porque cada campo
        recibe foco, blur y unos segundos de estabilización. Esta rutina reproduce
        únicamente esos eventos normales; no evita ni altera validaciones de UTEL.
        """

        footer = self._footer_locator(page)
        await footer.wait_for(state="visible", timeout=8000)

        name_field = await self._first_existing_footer_field(
            footer,
            ['[data-cy="textfieldInput"]', '#first_name', 'input[name="first_name"]'],
        )
        email_field = await self._first_existing_footer_field(
            footer,
            ['[data-cy="emailInput"]', '#email', 'input[type="email"]', 'input[name="email"]'],
        )
        phone_field = await self._first_existing_footer_field(
            footer,
            ['[data-cy="telephoneInput"]', '#phone', 'input[type="tel"]', 'input[name="phone"]'],
        )

        # Nombre y correo ya fueron llenados por Playwright. Darles foco y salir
        # con Tab fuerza los handlers onBlur/onChange que un usuario activa al
        # avanzar manualmente por el formulario.
        for field in (name_field, email_field):
            if field is None:
                continue
            await field.focus()
            await field.press("End")
            await field.press("Tab")
            await asyncio.sleep(0.2)

        # El teléfono es el campo que más suele tener validación/máscara propia.
        # Se vuelve a escribir de forma secuencial para que el componente reciba
        # eventos de teclado reales antes del blur final.
        if phone_field is not None:
            await phone_field.focus()
            await phone_field.fill("")
            await phone_field.press_sequentially(config.lead.phone, delay=35)
            await phone_field.press("Tab")
            await asyncio.sleep(0.35)

        with suppress(Exception):
            await page.evaluate(
                "() => { if (document.activeElement instanceof HTMLElement) document.activeElement.blur(); }"
            )

        # Dar tiempo a validaciones asíncronas y metadatos ocultos del formulario.
        # En el video el bot enviaba casi inmediatamente después del llenado,
        # mientras que el mismo lead enviado manualmente sí fue aceptado.
        await asyncio.sleep(3.0)

        # Si algún handler remontó FooterBLC durante el blur, restaurar y validar
        # el formulario una vez más antes de permitir el submit.
        await self._stabilize_footer_before_submit(page, config)

    async def _fill_utel_form(
        self,
        page: Any,
        form: Any,
        config: UtelQaConfig,
    ) -> None:
        await super()._fill_utel_form(page, form, config)
        if config.form_type == "footer":
            await self._stabilize_footer_before_submit(page, config)
            await self._settle_footer_contact_state(page, config)

    async def _surface_utel_feedback(self, page: Any) -> None:
        """Hace visible el toast sin hacer scroll ni cambiar el layout del form."""

        try:
            await page.evaluate(
                """() => {
                    const wanted = /error al enviar|contacta a soporte|env[ií]o correcto|pronto recibir|gracias|informaci[oó]n/i;
                    const manager = document.querySelector('#chakra-toast-manager-bottom');
                    const nodes = [
                      ...document.querySelectorAll('[role="alert"], [role="status"], .chakra-alert, .chakra-toast')
                    ].filter(node => node.getClientRects().length > 0 && wanted.test(node.innerText || node.textContent || ''));

                    if (manager && wanted.test(manager.innerText || manager.textContent || '')) {
                      manager.style.setProperty('position', 'fixed', 'important');
                      manager.style.setProperty('top', '88px', 'important');
                      manager.style.setProperty('right', '24px', 'important');
                      manager.style.setProperty('bottom', 'auto', 'important');
                      manager.style.setProperty('left', 'auto', 'important');
                      manager.style.setProperty('z-index', '2147483647', 'important');
                    }

                    for (const node of nodes) {
                      const container = node.closest('#chakra-toast-manager-bottom, .chakra-toast, .chakra-alert') || node;
                      container.style.setProperty('z-index', '2147483647', 'important');
                    }
                    return Boolean(manager || nodes.length);
                }"""
            )
            await asyncio.sleep(1.0)
        except Exception:
            return

    async def _wait_for_utel_submit_feedback(self, page: Any) -> str:
        """Conserva la detección estable y hace visible solo feedback real."""

        text = await super()._wait_for_utel_submit_feedback(page)
        await self._surface_utel_feedback(page)
        return text

    async def _submit_utel_form(
        self,
        page: Any,
        form: Any,
        should_stop: Callable[[], bool] | None = None,
    ) -> None:
        # Importante: NO maximizar aquí. Cambiar el tamaño después de llenar el
        # formulario provoca remontajes React y puede borrar el programa.
        try:
            await super()._submit_utel_form(page, form, should_stop)
        except UtelQaError as error:
            with suppress(Exception):
                await self._surface_utel_feedback(page)

            if error.stage != "utel_submit":
                raise

            message = str(error)
            normalized = message.casefold()
            explicit_rejection = (
                "utel confirmó que el formulario no fue aceptado" in normalized
                or "utel confirmo que el formulario no fue aceptado" in normalized
            )
            if not explicit_rejection:
                raise

            raise UtelQaError(
                "utel_submit",
                (
                    "Error al enviar / Contacta a soporte. "
                    f"{message} Leads Deploy reintentará este caso con otro "
                    "teléfono de prueba antes de marcarlo como fallo definitivo."
                ),
                error.selector,
            ) from error
