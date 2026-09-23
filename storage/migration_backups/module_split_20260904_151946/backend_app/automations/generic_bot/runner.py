"""Ejecutor sencillo de flujos configurables con Playwright para Python."""

import re
import unicodedata
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any

from ...config.settings import Settings
from ...schemas.bot import BotConfig, BotStep, BotStepResult
from ...services.logging_service import get_logger


class BotRunner:
    """Traduce pasos de negocio a acciones pequeñas y observables del navegador."""

    STEP_LABELS = {
        "goto": "Abrir URL",
        "click": "Hacer click",
        "hover": "Hacer hover",
        "check": "Marcar checkbox",
        "uncheck": "Desmarcar checkbox",
        "fill": "Rellenar campo",
        "select": "Seleccionar opción",
        "assert_text": "Verificar texto",
        "assert_url": "Verificar URL",
        "wait": "Esperar",
        "screenshot": "Tomar screenshot",
        "scroll": "Hacer scroll",
    }
    _open_session: dict[str, Any] | None = None

    def __init__(self, settings: Settings):
        self.settings = settings
        self.logger = get_logger()

    @classmethod
    async def _close_open_session(cls) -> None:
        """Cierra una sesión dejada abierta por una ejecución anterior."""

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
            # La ventana pudo haberse cerrado manualmente; en ese caso solo
            # liberamos las referencias y permitimos iniciar otra ejecución.
            pass
        finally:
            try:
                await session["playwright"].stop()
            except Exception:
                pass

    @asynccontextmanager
    async def _playwright_context(self, keep_open: dict[str, bool]):
        """Mantiene vivo Playwright cuando el usuario solicita revisión manual."""

        from playwright.async_api import async_playwright

        playwright = await async_playwright().start()
        try:
            yield playwright
        finally:
            if not keep_open["value"]:
                await playwright.stop()

    async def run(self, config: BotConfig) -> dict[str, Any]:
        """Ejecuta el flujo completo y devuelve un resultado sin traceback técnico."""

        started_at = datetime.now().isoformat(timespec="seconds")
        timer = perf_counter()
        step_results: list[BotStepResult] = []
        screenshots: list[str] = []
        page = None
        evidence_directory = self._evidence_directory(config.name)

        try:
            try:
                from playwright.async_api import TimeoutError as PlaywrightTimeoutError
                from playwright.async_api import expect
            except ImportError as error:
                raise RuntimeError(
                    "Playwright no está instalado. Ejecuta `python -m pip install -r backend/requirements.txt` "
                    "y después `python -m playwright install chromium`."
                ) from error

            await self._close_open_session()
            # Puede cambiar a True cuando un paso falle para conservar la
            # sesión y permitir una revisión manual del estado parcial.
            # Los scripts se ejecutan siempre en segundo plano.
            keep_open = {"value": False}
            async with self._playwright_context(keep_open) as playwright:
                browser = None
                context = None
                launch_headless = True
                if config.browser == "chrome":
                    # Usamos una carpeta propia para no tocar el perfil personal
                    # de Chrome ni provocar conflictos con una ventana abierta.
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
                try:
                    if context is None:
                        context = await browser.new_context(viewport={"width": 1440, "height": 900})
                    page = await context.new_page()
                    page.set_default_timeout(15000)

                    for index, step in enumerate(config.steps, start=1):
                        self.logger.info("Bot %s - paso %s: %s", config.name, index, self.STEP_LABELS[step.type])
                        try:
                            screenshot = await self._execute_step(
                                page,
                                step,
                                index,
                                config.url,
                                evidence_directory,
                                expect,
                            )
                            if screenshot:
                                screenshots.append(screenshot)
                            step_results.append(
                                BotStepResult(
                                    step_number=index,
                                    type=step.type,
                                    status="PASS",
                                    message=f"{self.STEP_LABELS[step.type]} completado.",
                                    screenshot=screenshot,
                                )
                            )
                        except PlaywrightTimeoutError:
                            failure_screenshot = await self._take_failure_screenshot(page, index, evidence_directory)
                            if failure_screenshot:
                                screenshots.append(failure_screenshot)
                            step_results.append(
                                BotStepResult(
                                    step_number=index,
                                    type=step.type,
                                    status="FAIL",
                                    message="Se agotó el tiempo esperando el elemento o resultado.",
                                    screenshot=failure_screenshot,
                                )
                            )
                            break
                        except Exception as error:  # Playwright puede emitir varios errores específicos.
                            self.logger.exception("Falló el paso %s del bot %s", index, config.name)
                            failure_screenshot = await self._take_failure_screenshot(page, index, evidence_directory)
                            if failure_screenshot:
                                screenshots.append(failure_screenshot)
                            step_results.append(
                                BotStepResult(
                                    step_number=index,
                                    type=step.type,
                                    status="FAIL",
                                    message=self._friendly_error(error),
                                    screenshot=failure_screenshot,
                                )
                            )
                            break
                finally:
                    failed_run = any(result.status == "FAIL" for result in step_results)
                    preserve_browser = False
                    keep_open["value"] = preserve_browser
                    if preserve_browser and context is not None:
                        BotRunner._open_session = {
                            "playwright": playwright,
                            "context": context,
                            "browser": browser,
                        }
                        self.logger.info("El navegador quedó abierto para revisión manual.")
                    else:
                        if context is not None:
                            await context.close()
                        if browser is not None:
                            await browser.close()

            status = "PASS" if step_results and all(result.status == "PASS" for result in step_results) and len(step_results) == len(config.steps) else "FAIL"
            summary = "Bot finalizado correctamente." if status == "PASS" else "El bot falló en uno de sus pasos."
        except Exception as error:
            self.logger.exception("No se pudo iniciar el bot %s", config.name)
            status = "FAIL"
            summary = self._friendly_error(error)

        if BotRunner._open_session:
            summary += " El navegador quedó abierto para revisión manual."

        finished_at = datetime.now().isoformat(timespec="seconds")
        return {
            "status": status,
            "summary": summary,
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_seconds": round(perf_counter() - timer, 2),
            "steps": step_results,
            "screenshots": screenshots,
        }

    async def _execute_step(
        self,
        page: Any,
        step: BotStep,
        index: int,
        initial_url: str,
        evidence_directory: Path,
        expect: Any,
    ) -> str | None:
        """Ejecuta una acción soportada y devuelve la evidencia creada, si existe."""

        if step.type == "goto":
            await page.goto(step.target or initial_url, wait_until="domcontentloaded")
        elif step.type == "click":
            await (await self._locator(page, step.target)).click()
        elif step.type == "hover":
            await (await self._locator(page, step.target)).hover()
            await page.wait_for_timeout(250)
        elif step.type == "check":
            await self._set_checkbox(page, step.target, checked=True)
        elif step.type == "uncheck":
            await self._set_checkbox(page, step.target, checked=False)
        elif step.type == "fill":
            # Un enlace previo puede haber navegado a una SPA cuyo formulario
            # todavía se está montando. Esperamos y resolvemos el campo otra vez
            # antes de escribir para no llenar una copia transitoria.
            await page.wait_for_timeout(350)
            locator = await self._locator(page, step.target)
            await locator.fill(step.value)
            if step.value:
                await page.wait_for_timeout(350)
                locator = await self._locator(page, step.target)
                try:
                    current_value = await locator.input_value()
                except Exception:
                    current_value = step.value
                if current_value != step.value:
                    await locator.fill(step.value, force=True)
                    await page.wait_for_timeout(150)
                    current_value = await locator.input_value()
                    if current_value != step.value:
                        raise RuntimeError("El valor no permaneció en el campo visible.")
        elif step.type == "select":
            await (await self._locator(page, step.target)).select_option(step.value)
        elif step.type == "assert_text":
            await expect(await self._locator(page, step.target)).to_contain_text(step.value)
        elif step.type == "assert_url":
            await expect(page).to_have_url(step.target)
        elif step.type == "wait":
            milliseconds = self._positive_integer(step.value, "El tiempo de espera debe ser mayor que cero.")
            await page.wait_for_timeout(milliseconds)
        elif step.type == "screenshot":
            return await self._take_screenshot(page, step.value or f"paso-{index}", evidence_directory, index)
        elif step.type == "scroll":
            scroll_position = self._non_negative_integer(step.value, "La posición del scroll debe ser un número válido.")
            await page.evaluate("(position) => window.scrollTo(0, position)", scroll_position)
            await page.wait_for_timeout(300)
        else:
            raise ValueError(f"Tipo de paso no soportado: {step.type}")
        return None

    @staticmethod
    async def _visible(locator: Any) -> Any:
        """Elige el primer elemento visible cuando la página tiene duplicados responsivos."""

        first_visible = None
        for index in range(await locator.count()):
            candidate = locator.nth(index)
            if not await candidate.is_visible():
                continue
            if first_visible is None:
                first_visible = candidate
            is_in_viewport = await candidate.evaluate(
                """(element) => {
                    const rect = element.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0
                        && rect.right > 0 && rect.bottom > 0
                        && rect.left < window.innerWidth && rect.top < window.innerHeight;
                }"""
            )
            if is_in_viewport:
                return candidate
        return first_visible or locator.first

    @staticmethod
    async def _locator(page: Any, target: str) -> Any:
        """Convierte una notación simple en un locator legible para el equipo QA."""

        if not target:
            raise ValueError("El paso necesita un selector, rol o texto.")
        if target.startswith("text="):
            return await BotRunner._visible(page.get_by_text(target[5:], exact=True))
        if target.startswith("label="):
            return await BotRunner._visible(page.get_by_label(target[6:], exact=True))
        if target.startswith("testid="):
            return await BotRunner._visible(page.get_by_test_id(target[7:]))
        if target.startswith("role="):
            match = re.fullmatch(r"role=([^\[]+)(?:\[name=(.*)\])?", target)
            if not match:
                raise ValueError("Formato de rol inválido. Usa role=link[name=Modalidad].")
            role, name = match.groups()
            role = role.strip()
            if role in {"group", "region", "main", "navigation", "list", "listitem"} and name:
                # Compatibilidad con grabaciones antiguas que tomaron un contenedor completo.
                first_text = name.strip().split()[0]
                return await BotRunner._visible(page.get_by_text(first_text, exact=True))
            return await BotRunner._visible(page.get_by_role(role, name=name.strip() if name else None, exact=True))
        if target.startswith("css="):
            css_target = target[4:]
            # Algunos IDs válidos en HTML contienen espacios. En CSS, `#id con espacios`
            # se interpreta como una ruta de descendientes, así que recuperamos el ID
            # mediante un selector de atributo para mantener compatibilidad con flujos ya grabados.
            if css_target.startswith("#") and " " in css_target[1:]:
                element_id = css_target[1:].replace("\\", "\\\\").replace('"', '\\"')
                return await BotRunner._visible(page.locator(f'[id="{element_id}"]'))
            return await BotRunner._visible(page.locator(css_target))
        # Como último recurso se acepta CSS directo, útil para selectores sencillos.
        return await BotRunner._visible(page.locator(target))

    @classmethod
    async def _set_checkbox(cls, page: Any, target: str, checked: bool) -> None:
        """Marca o desmarca incluso si un control visual cubre el input nativo."""

        changed_with_label = await page.evaluate(
            """({ target, checked }) => {
                const inViewport = (element) => {
                    const clickable = element.closest("label") || element;
                    const rect = clickable.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0
                        && rect.right > 0 && rect.bottom > 0
                        && rect.left < window.innerWidth && rect.top < window.innerHeight;
                };
                const checkboxOrRadio = (element) => element instanceof HTMLInputElement
                    && ["checkbox", "radio"].includes(element.type);
                let candidates = [];
                if (target.startsWith("css=")) {
                    try {
                        candidates = [...document.querySelectorAll(target.slice(4))]
                            .filter(checkboxOrRadio);
                    } catch {
                        candidates = [];
                    }
                }
                let input = candidates.find(inViewport);
                // Compatibilidad con grabaciones antiguas cuyo selector estructural
                // coincide con una copia del formulario fuera de pantalla.
                if (!input) {
                    input = [...document.querySelectorAll('input[type="checkbox"], input[type="radio"]')]
                        .find(inViewport);
                }
                if (!input) return false;
                if (input.checked !== checked) {
                    const label = input.closest("label");
                    (label || input).click();
                }
                return true;
            }""",
            {"target": target, "checked": checked},
        )
        if changed_with_label:
            await page.wait_for_timeout(120)
            checkbox_matches_state = await page.evaluate(
                """({ checked }) => [...document.querySelectorAll('input[type="checkbox"], input[type="radio"]')]
                    .some((input) => {
                        const clickable = input.closest("label") || input;
                        const rect = clickable.getBoundingClientRect();
                        const inViewport = rect.width > 0 && rect.height > 0
                            && rect.right > 0 && rect.bottom > 0
                            && rect.left < window.innerWidth && rect.top < window.innerHeight;
                        return inViewport && input.checked === checked;
                    })""",
                {"checked": checked},
            )
            if checkbox_matches_state:
                return

        locator = await cls._locator(page, target)
        action = locator.check if checked else locator.uncheck
        try:
            await action(force=True)
        except Exception:
            # Algunos diseños dejan el input debajo de un elemento decorativo
            # que intercepta el clic; el modo forzado mantiene sus eventos.
            await action()

        if await locator.is_checked() != checked:
            raise RuntimeError("No se pudo cambiar el estado del checkbox.")

    def _evidence_directory(self, bot_name: str) -> Path:
        """Crea una carpeta diaria para no mezclar evidencias de distintos bots."""

        directory = self.settings.storage_dir / "screenshots" / "bots" / datetime.now().date().isoformat() / self._slug(bot_name)
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    async def _take_screenshot(self, page: Any, name: str, directory: Path, index: int) -> str:
        """Guarda una captura completa y devuelve una ruta relativa para la interfaz."""

        file_path = directory / f"{index:02d}-{self._slug(name)}.png"
        await page.screenshot(path=str(file_path), full_page=True)
        return file_path.relative_to(self.settings.storage_dir.parent).as_posix()

    async def _take_failure_screenshot(self, page: Any, index: int, directory: Path) -> str | None:
        """Intenta conservar evidencia incluso cuando un paso falla."""

        if page is None:
            return None
        try:
            return await self._take_screenshot(page, "fallo", directory, index)
        except Exception:
            self.logger.exception("No se pudo guardar screenshot del fallo")
            return None

    @staticmethod
    def _positive_integer(value: str, message: str) -> int:
        try:
            number = int(value)
        except (TypeError, ValueError) as error:
            raise ValueError(message) from error
        if number <= 0:
            raise ValueError(message)
        return number

    @staticmethod
    def _non_negative_integer(value: str, message: str) -> int:
        """Convierte la posición vertical capturada sin aceptar valores inválidos."""

        try:
            number = int(value)
        except (TypeError, ValueError) as error:
            raise ValueError(message) from error
        if number < 0:
            raise ValueError(message)
        return number

    @staticmethod
    def _slug(value: str) -> str:
        normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
        return re.sub(r"[^a-zA-Z0-9_-]+", "-", normalized).strip("-").lower() or "bot"

    @staticmethod
    def _friendly_error(error: Exception) -> str:
        """Evita devolver trazas internas, pero conserva una pista útil para QA."""

        message = str(error).strip()
        return message[:300] if message else "Ocurrió un error durante la automatización."
