"""Runner de capturas semanales con Playwright."""

import asyncio
import re
import secrets
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Callable
from urllib.parse import urlparse

from ...schemas.weekly_auto import WeeklyAutoConfig
from ...services.logging_service import get_logger


class WeeklyAutoError(RuntimeError):
    """Error de negocio con contexto de URL."""

    def __init__(self, url: str, message: str):
        super().__init__(message)
        self.url = url


class WeeklyAutoRunner:
    """Captura pantallas completas de una lista de URLs."""

    def __init__(self, settings):
        self.settings = settings
        self.logger = get_logger()
        self.evidence_directory: Path | None = None
        self.results: list[dict[str, Any]] = []
        self.screenshots: list[str] = []

    async def run(self, config: WeeklyAutoConfig, progress_callback: Callable[[dict[str, Any]], Any] | None = None) -> dict[str, Any]:
        """Ejecuta la corrida completa y devuelve un resumen serializable."""

        started_at = datetime.now().isoformat(timespec="seconds")
        timer = perf_counter()
        self.results = []
        self.screenshots = []
        self.evidence_directory = self._evidence_directory(config.name)
        urls = self._build_urls(config)
        if not urls:
            raise WeeklyAutoError("", "No hay URLs para procesar.")

        max_urls = config.max_urls
        if max_urls is not None and max_urls > 0:
            urls = urls[:max_urls]

        try:
            from playwright.async_api import async_playwright
        except ImportError as error:
            raise RuntimeError(
                "Playwright no está instalado. Ejecuta `python -m pip install -r backend/requirements.txt` y luego `python -m playwright install chromium`."
            ) from error

        try:
            await self._run_with_playwright(urls, config, progress_callback)
            status = "PASS" if all(item["status"] != "FAIL" for item in self.results) else "FAIL"
            summary = (
                f"Weekly Auto completado: {sum(item['status']=='PASS' for item in self.results)} éxitos, "
                f"{sum(item['status']=='FAIL' for item in self.results)} errores, "
                f"{sum(item['status']=='SKIPPED' for item in self.results)} omitidos."
            )
        except asyncio.CancelledError:
            for index in range(len(urls) - len(self.results), len(urls)):
                self.results.append(
                    {
                        "index": index + 1,
                        "url": urls[index],
                        "status": "SKIPPED",
                        "message": "Ejecución cancelada por el usuario",
                        "screenshot": None,
                        "elapsed_seconds": 0.0,
                    },
                )
            status = "CANCELLED"
            summary = "Ejecución cancelada por el usuario."
        except Exception as error:  # noqa: BLE001
            self.logger.exception("Fallo al correr Weekly Auto.")
            status = "FAIL"
            summary = f"Weekly Auto terminó con error: {error}"

        elapsed = round(perf_counter() - timer, 2)
        total = len(urls)
        successful = len([item for item in self.results if item["status"] == "PASS"])
        failed = len([item for item in self.results if item["status"] == "FAIL"])
        skipped = len([item for item in self.results if item["status"] == "SKIPPED"])
        return {
            "status": status,
            "summary": summary,
            "started_at": started_at,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "duration_seconds": elapsed,
            "total_urls": total,
            "completed": len([item for item in self.results if item["status"] != "SKIPPED"]),
            "successful": successful,
            "failed": failed,
            "skipped": skipped,
            "results": self.results,
            "screenshots": self.screenshots,
        }

    def _build_urls(self, config: WeeklyAutoConfig) -> list[str]:
        """Resuelve la lista final y limpia duplicados."""

        configured_urls = [url.strip() for url in config.urls if url.strip()]
        if config.use_default_urls:
            default_file = Path(__file__).resolve().parent / "default_urls.txt"
            if default_file.is_file():
                configured_urls = [
                    line.strip()
                    for line in default_file.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                ] + configured_urls
        return list(dict.fromkeys(configured_urls))

    async def _run_with_playwright(self, urls: list[str], config: WeeklyAutoConfig, progress_callback: Callable[[dict[str, Any]], Any] | None = None) -> None:
        """Ejecuta el flujo de navegación y captura con Playwright."""

        from playwright.async_api import TimeoutError as PlaywrightTimeoutError
        from playwright.async_api import async_playwright

        self.logger.info("Iniciando Weekly Auto con %s URLs.", len(urls))
        keep_open = {"value": False}
        async with async_playwright() as playwright:
            browser = None
            context = None
            try:
                if config.browser == "chrome":
                    profile_directory = self.settings.storage_dir / "browser_profiles" / "weekly-auto-chrome"
                    profile_directory.mkdir(parents=True, exist_ok=True)
                    context = await playwright.chromium.launch_persistent_context(
                        str(profile_directory),
                        channel="chrome",
                        headless=config.headless if not config.keep_browser_open else False,
                        viewport={"width": config.viewport_width, "height": config.viewport_height},
                    )
                else:
                    browser_type = getattr(playwright, config.browser)
                    browser = await browser_type.launch(headless=config.headless if not config.keep_browser_open else False)
                    context = await browser.new_context(viewport={"width": config.viewport_width, "height": config.viewport_height})

                for index, url in enumerate(urls, start=1):
                    start = perf_counter()
                    page = None
                    current = {
                        "index": index,
                        "url": url,
                        "status": "FAIL",
                        "message": "",
                        "screenshot": None,
                        "elapsed_seconds": 0.0,
                    }

                    try:
                        if not self._is_valid_url(url):
                            raise WeeklyAutoError(url, "URL inválida. Solo se permiten direcciones HTTP o HTTPS.")
                        page = await context.new_page()
                        page.set_default_timeout(30_000)
                        await page.goto(url, wait_until="domcontentloaded")
                        await self._progressive_scroll(page, config.scroll_pause_ms)
                        await self._stabilize_page(page, config.settle_wait_ms)
                        screenshot_path = await self._save_screenshot(page, url, index)
                        current.update(
                            {
                                "status": "PASS",
                                "message": "Captura completada",
                                "screenshot": screenshot_path,
                            }
                        )
                        self.logger.info("Captura OK: %s", url)
                    except PlaywrightTimeoutError as error:
                        self.logger.warning("Timeout en %s: %s", url, error)
                        current["status"] = "FAIL"
                        current["message"] = f"Timeout al procesar la URL: {error}"
                    except WeeklyAutoError as error:
                        current["status"] = "FAIL"
                        current["message"] = str(error)
                    except Exception as error:  # noqa: BLE001
                        self.logger.exception("Error procesando %s", url)
                        current["status"] = "FAIL"
                        current["message"] = str(error)
                    finally:
                        if page is not None and not page.is_closed():
                            try:
                                await page.close()
                            except Exception:  # noqa: BLE001 - el contexto hará la limpieza final
                                self.logger.warning("No fue posible cerrar la pestaña de %s.", url, exc_info=True)

                    current["elapsed_seconds"] = round(perf_counter() - start, 2)
                    self.results.append(current)
                    if progress_callback:
                        progress_callback(
                            {
                                "index": index,
                                "total": len(urls),
                                "url": current["url"],
                                "status": current["status"],
                                "message": current["message"],
                                "screenshot": current["screenshot"],
                                "elapsed_seconds": current["elapsed_seconds"],
                            }
                        )

                    if index < len(urls) and config.inter_url_delay_seconds > 0:
                        await asyncio.sleep(config.inter_url_delay_seconds)
            finally:
                if context is not None and not config.keep_browser_open:
                    await context.close()
                if browser is not None and not config.keep_browser_open:
                    await browser.close()
                keep_open["value"] = config.keep_browser_open
                if keep_open["value"]:
                    self.logger.info("keep_browser_open activo en Weekly Auto; la sesión quedara abierta al finalizar.")

    async def _progressive_scroll(self, page: Any, pause_ms: int) -> None:
        """Realiza scroll por pantalla para cargar contenido lazy."""

        pause_ms = max(100, pause_ms)
        total_height = await page.evaluate("() => Math.max(document.body.scrollHeight, document.documentElement.scrollHeight)")
        viewport_height = await page.evaluate("() => window.innerHeight")
        if not isinstance(total_height, (int, float)) or not isinstance(viewport_height, (int, float)) or viewport_height <= 0:
            return
        current_position = 0
        # Evita que una página con scroll infinito bloquee toda la corrida.
        max_steps = 100
        try:
            for _ in range(max_steps):
                if current_position >= total_height:
                    break
                current_position = total_height
                await page.evaluate("position => window.scrollTo(0, position)", current_position)
                await page.wait_for_timeout(pause_ms)
                new_height = await page.evaluate("() => Math.max(document.body.scrollHeight, document.documentElement.scrollHeight)")
                if isinstance(new_height, (int, float)) and new_height > total_height:
                    total_height = new_height
            else:
                self.logger.warning("Se alcanzó el límite de scroll progresivo; se continuará con la captura.")
        finally:
            # Se conserva la posición al fondo para que la captura vea el estado final.
            pass

    async def _stabilize_page(self, page: Any, pause_ms: int) -> None:
        """Dale tiempo al DOM para resolver cambios tras el scroll."""

        if pause_ms > 0:
            await page.wait_for_timeout(pause_ms)

    async def _save_screenshot(self, page: Any, url: str, index: int) -> str:
        if self.evidence_directory is None:
            raise WeeklyAutoError(url, "No se pudo determinar el directorio de evidencias.")
        path = self.evidence_directory / f"{index:03d}_{self._safe_name(url)}_web.png"
        try:
            await page.screenshot(path=str(path), full_page=True, animations="disabled")
            if not path.is_file() or path.stat().st_size == 0:
                raise OSError("Playwright no generó un archivo PNG válido.")
            relative = path.relative_to(self.settings.storage_dir).as_posix()
            self.screenshots.append(relative)
            return relative
        except Exception:
            self.logger.exception("No fue posible guardar screenshot para %s", url)
            raise WeeklyAutoError(url, "No fue posible guardar la captura de pantalla.") from None

    @staticmethod
    def _safe_name(url: str) -> str:
        parsed = urlparse(url)
        clean = f"{parsed.netloc}{parsed.path}".strip("/")
        if not clean:
            clean = parsed.netloc or "captura"
        clean = re.sub(r"[^a-zA-Z0-9._-]+", "-", clean)
        return clean[:80] or f"link-{secrets.token_hex(3)}"

    @staticmethod
    def _is_valid_url(url: str) -> bool:
        parsed = urlparse(url)
        return parsed.scheme.lower() in {"http", "https"} and bool(parsed.netloc)

    def _evidence_directory(self, name: str) -> Path:
        now = datetime.now()
        directory = (
            self.settings.storage_dir
            / "screenshots"
            / "weekly_auto"
            / now.date().isoformat()
            / f"{secrets.token_hex(3)}_{re.sub(r'[^a-zA-Z0-9_-]+', '-', name).strip('-').lower()[:36] or 'weekly-auto'}"
        )
        directory.mkdir(parents=True, exist_ok=True)
        return directory
