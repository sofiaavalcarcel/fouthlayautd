"""Grabador visual que convierte interacciones del navegador en pasos del bot."""

from __future__ import annotations

import re
from pathlib import Path
from uuid import uuid4

from ...config.settings import Settings
from ...schemas.bot import BotStep
from ...schemas.recorder import RecorderEvent, RecorderStartRequest
from ...services.logging_service import get_logger
from .runner import BotRunner


# El script se ejecuta dentro de la página, resalta el elemento bajo el cursor
# y envía un locator legible al backend cuando el usuario hace click o escribe.
RECORDER_SCRIPT = r"""
(() => {
  if (window.__qaRecorderInstalled) return;
  window.__qaRecorderInstalled = true;
  let highlightedElement = null;
  let highlightedOutline = "";

  const clean = (value, max = 120) => (value || "").replace(/\s+/g, " ").trim().slice(0, max);
  const cssAttributeValue = (value) => String(value || "").replace(/\\/g, "\\\\").replace(/"/g, '\\"');
  const interactiveRoles = ["button", "link", "checkbox", "radio", "tab", "menuitem", "textbox", "combobox", "option"];

  function clickableElement(element) {
    let current = element;
    while (current && current !== document.body) {
      const role = current.getAttribute?.("role");
      const styles = window.getComputedStyle(current);
      if (
        current.matches?.("a,button,input,textarea,select,label") ||
        interactiveRoles.includes(role) ||
        current.hasAttribute?.("onclick") ||
        current.hasAttribute?.("tabindex") ||
        styles.cursor === "pointer"
      ) return current;
      current = current.parentElement;
    }
    return element;
  }

  function cssPath(element) {
    const parts = [];
    let current = element;
    while (current && current.nodeType === 1 && current !== document.body && parts.length < 5) {
      let part = current.tagName.toLowerCase();
      const siblings = current.parentElement ? [...current.parentElement.children].filter((item) => item.tagName === current.tagName) : [];
      if (siblings.length > 1) part += `:nth-of-type(${siblings.indexOf(current) + 1})`;
      parts.unshift(part);
      current = current.parentElement;
    }
    return `css=${parts.join(" > ")}`;
  }

  function formScopedSelector(element, selector) {
    const form = element.closest?.("form[id]");
    const formId = clean(form?.getAttribute("id"), 180);
    if (!formId) return selector;
    const formSelector = `form[id="${cssAttributeValue(formId)}"]`;
    if (document.querySelectorAll(formSelector).length !== 1) return selector;
    return `${formSelector} ${selector}`;
  }

  function describe(element, preferStructure = false) {
    const testId = element.getAttribute("data-testid") || element.getAttribute("data-test-id");
    if (testId) return { target: `testid=${clean(testId, 180)}`, label: clean(element.innerText || element.getAttribute("aria-label")) };

    const id = element.getAttribute("id");
    if (id) {
      const selector = `[id="${cssAttributeValue(clean(id, 180))}"]`;
      return { target: `css=${formScopedSelector(element, selector)}`, label: clean(element.innerText || element.getAttribute("aria-label")) };
    }

    const name = element.getAttribute("name");
    if (name) {
      const selector = `${element.tagName.toLowerCase()}[name="${clean(name, 120)}"]`;
      return { target: `css=${formScopedSelector(element, selector)}`, label: clean(element.innerText || name) };
    }

    const text = clean(element.innerText || element.getAttribute("aria-label"));
    const role = element.getAttribute("role");
    if (role && interactiveRoles.includes(role) && text) return { target: `role=${clean(role, 40)}[name=${text}]`, label: text };
    if (!preferStructure && text) return { target: `text=${text}`, label: text };
    return { target: cssPath(element), label: element.tagName.toLowerCase() };
  }

  function installBanner() {
    if (!document.body || document.querySelector("#qa-recorder-banner")) return;
    const banner = document.createElement("div");
    banner.id = "qa-recorder-banner";
    banner.textContent = "QA Recorder · pasa el cursor y haz click para agregar pasos";
    Object.assign(banner.style, {
      position: "fixed", top: "10px", right: "10px", zIndex: "2147483647",
      padding: "8px 12px", borderRadius: "7px", color: "white",
      background: "#1d4ed8", font: "12px Arial", boxShadow: "0 3px 12px #0006",
      pointerEvents: "none"
    });
    document.body.appendChild(banner);
  }

  function isIgnored(element) {
    return !element || element.closest("#qa-recorder-banner") || element.closest("input[type=password]");
  }

  document.addEventListener("mouseover", (event) => {
    const hovered = event.target.closest?.("a,button,input,textarea,select,[role],h1,h2,h3,p,li") || event.target;
    const element = clickableElement(hovered);
    if (isIgnored(element)) return;
    if (highlightedElement) highlightedElement.style.outline = highlightedOutline;
    highlightedElement = element;
    highlightedOutline = element.style.outline;
    element.style.outline = "2px solid #2563eb";
  }, true);

  document.addEventListener("click", (event) => {
    const candidate = event.target.closest?.("a,button,input,textarea,select,label,[role='button'],[role='link'],[role='checkbox'],[role='radio'],[role='tab'],[role='menuitem']") || event.target;
    const clicked = clickableElement(candidate);
    const element = clicked?.tagName?.toLowerCase() === "label" && clicked.control ? clicked.control : clicked;
    if (isIgnored(element)) return;
    // Solo aceptamos un click físico del botón principal; pasar el cursor,
    // activar con teclado o un click sintético no debe crear un paso.
    if (event.detail < 1 || (typeof event.button === "number" && event.button !== 0)) return;
    const tagName = element.tagName.toLowerCase();
    const isNativeCheckbox = tagName === "input" && ["checkbox", "radio"].includes(element.type);
    const isAriaCheckbox = element.getAttribute("role") === "checkbox";
    if (isNativeCheckbox || isAriaCheckbox) {
      const description = describe(element, true);
      // El listener se ejecuta en captura, antes del cambio nativo de estado.
      // Diferimos la lectura para registrar si terminó marcado o desmarcado.
      window.setTimeout(() => {
        const checked = isNativeCheckbox ? element.checked : element.getAttribute("aria-checked") === "true";
        const type = checked ? "check" : "uncheck";
        window.__qaRecorderEvent?.({ type, ...description, value: "" });
      }, 0);
      return;
    }
    if (tagName === "input" && ["submit", "button"].includes(element.type)) return;
    if (tagName === "input" || tagName === "textarea") {
      const description = describe(element);
      window.__qaRecorderEvent?.({ type: "fill", ...description, value: "" });
      return;
    }
    if (tagName === "select") return;
    const description = describe(element, true);
    window.__qaRecorderEvent?.({ type: "click", ...description, value: "" });
  }, true);

  document.addEventListener("input", (event) => {
    const element = event.target;
    if (!element || !["INPUT", "TEXTAREA"].includes(element.tagName) || element.type === "password") return;
    window.clearTimeout(element.__qaRecorderTimer);
    element.__qaRecorderTimer = window.setTimeout(() => {
      const description = describe(element);
      // El valor se deja vacío para que el usuario lo defina dentro de Electron.
      window.__qaRecorderEvent?.({ type: "fill", ...description, value: "" });
    }, 300);
  }, true);

  let scrollTimer;
  window.addEventListener("scroll", () => {
    window.clearTimeout(scrollTimer);
    scrollTimer = window.setTimeout(() => {
      window.__qaRecorderEvent?.({ type: "scroll", target: "window", value: String(window.scrollY), label: `Y=${window.scrollY}px` });
    }, 500);
  }, { passive: true });

  document.addEventListener("change", (event) => {
    const element = event.target;
    if (!element || element.tagName !== "SELECT") return;
    const description = describe(element);
    // Las opciones se seleccionarán después desde la configuración del bot.
    window.__qaRecorderEvent?.({ type: "select", ...description, value: element.value || "" });
  }, true);

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", installBanner, { once: true });
  else installBanner();
})();
"""


class RecorderSession:
    """Mantiene un navegador visible y los eventos capturados por una sesión."""

    def __init__(self, session_id: str, settings: Settings, config: RecorderStartRequest):
        self.session_id = session_id
        self.settings = settings
        self.config = config
        self.events: list[RecorderEvent] = []
        self.error: str | None = None
        self.active = False
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.logger = get_logger()

    async def start(self) -> None:
        """Abre el navegador y registra el binding que recibe eventos del DOM."""

        try:
            from playwright.async_api import async_playwright

            self.playwright = await async_playwright().start()
            if self.config.browser == "chrome":
                profile_directory = self.settings.storage_dir / "browser_profiles" / "chrome-qa"
                profile_directory.mkdir(parents=True, exist_ok=True)
                self.context = await self.playwright.chromium.launch_persistent_context(
                    str(profile_directory),
                    channel="chrome",
                    headless=False,
                    viewport={"width": 1440, "height": 900},
                )
            else:
                browser_type = getattr(self.playwright, self.config.browser)
                self.browser = await browser_type.launch(headless=False)
                self.context = await self.browser.new_context(viewport={"width": 1440, "height": 900})

            await self.context.add_init_script(RECORDER_SCRIPT)
            self.page = await self.context.new_page()
            self.page.set_default_timeout(15000)

            async def receive_event(source, payload):
                if self.active:
                    self.add_event(payload)

            await self.page.expose_binding("__qaRecorderEvent", receive_event)
            if self.config.steps:
                await self._replay_steps()
            else:
                await self.page.goto(self.config.url, wait_until="domcontentloaded")
            self.active = True
            self.logger.info("Grabador iniciado: %s", self.session_id)
        except Exception as error:
            self.error = self._friendly_error(error)
            await self.close()
            raise RuntimeError(self.error) from error

    async def _replay_steps(self) -> None:
        """Reproduce el flujo previo para continuar desde su último estado."""

        if not self.config.steps:
            await self.page.goto(self.config.url, wait_until="domcontentloaded")
            return

        for step in self.config.steps:
            if step.type == "goto":
                await self.page.goto(step.target or self.config.url, wait_until="domcontentloaded")
            elif step.type == "click":
                await (await BotRunner._locator(self.page, step.target)).click()
            elif step.type == "hover":
                await (await BotRunner._locator(self.page, step.target)).hover()
                await self.page.wait_for_timeout(250)
            elif step.type == "check":
                await BotRunner._set_checkbox(self.page, step.target, checked=True)
            elif step.type == "uncheck":
                await BotRunner._set_checkbox(self.page, step.target, checked=False)
            elif step.type == "fill":
                await (await BotRunner._locator(self.page, step.target)).fill(step.value)
            elif step.type == "select" and step.value:
                await (await BotRunner._locator(self.page, step.target)).select_option(step.value)
            elif step.type == "wait":
                await self.page.wait_for_timeout(int(step.value))
            elif step.type == "scroll":
                await self.page.evaluate("(position) => window.scrollTo(0, position)", int(step.value))

        await self.page.wait_for_timeout(300)

    def add_event(self, payload: dict) -> None:
        """Filtra y limita la información capturada antes de conservarla."""

        try:
            event = RecorderEvent.model_validate(payload)
        except Exception:
            return
        if event.type == "scroll" and self.events and self.events[-1].type == "scroll":
            # Reemplazamos el último scroll mientras el usuario sigue bajando,
            # para convertir una rueda larga en un único paso útil.
            self.events[-1] = event
            return
        if self.events and self.events[-1].type == event.type and self.events[-1].target == event.target and self.events[-1].value == event.value:
            return
        self.events.append(event)

    def get_events(self) -> list[RecorderEvent]:
        """Devuelve una copia para que la respuesta HTTP no modifique la sesión."""

        return list(self.events)

    async def stop(self) -> list[BotStep]:
        """Cierra el navegador y convierte eventos en pasos ejecutables."""

        steps = [BotStep(type="goto", target=self.config.url)]
        steps.extend(BotStep(type=event.type, target=event.target, value=event.value) for event in self.events)
        await self.close()
        return steps

    async def close(self) -> None:
        """Libera la sesión sin borrar el perfil persistente de Chrome."""

        self.active = False
        try:
            if self.context is not None:
                await self.context.close()
            elif self.browser is not None:
                await self.browser.close()
        finally:
            if self.playwright is not None:
                await self.playwright.stop()
            self.context = None
            self.browser = None
            self.page = None
            self.playwright = None

    @staticmethod
    def _friendly_error(error: Exception) -> str:
        message = str(error).strip()
        return re.sub(r"\s+", " ", message)[:300] or "No se pudo abrir el navegador grabador."


class RecorderManager:
    """Administra una sesión de grabación activa por aplicación."""

    def __init__(self):
        self.sessions: dict[str, RecorderSession] = {}

    async def start(self, settings: Settings, config: RecorderStartRequest) -> RecorderSession:
        """Cierra una grabación anterior y abre una nueva sesión."""

        await self.close_all()
        session = RecorderSession(str(uuid4()), settings, config)
        await session.start()
        self.sessions[session.session_id] = session
        return session

    def get(self, session_id: str) -> RecorderSession | None:
        """Busca una sesión sin exponer el diccionario interno."""

        return self.sessions.get(session_id)

    async def stop(self, session_id: str) -> list[BotStep]:
        """Convierte y cierra una sesión concreta."""

        session = self.sessions.pop(session_id, None)
        if session is None:
            raise KeyError(session_id)
        return await session.stop()

    async def close_all(self) -> None:
        """Cierra sesiones al reiniciar FastAPI o al comenzar otra grabación."""

        sessions = list(self.sessions.values())
        self.sessions.clear()
        for session in sessions:
            await session.close()
