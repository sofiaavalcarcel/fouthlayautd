/** Presentación aislada de Leads Deploy. No lee ni modifica la configuración del bot. */
const STYLE_ID = "leads-deploy-visual-style";
let activePresentation = null;

export function initializeLeadsDeployVisuals() {
  const view = document.querySelector("#view-leads-deploy");
  if (activePresentation?.view === view && view?.isConnected) return activePresentation;
  activePresentation?.destroy();
  if (!view) return null;

  let stylesheet = document.getElementById(STYLE_ID);
  const ownsStylesheet = !stylesheet;
  if (!stylesheet) {
    stylesheet = document.createElement("link");
    stylesheet.id = STYLE_ID;
    stylesheet.rel = "stylesheet";
    stylesheet.href = new URL("./visual.css?v=reference-1", import.meta.url).href;
    document.head.append(stylesheet);
  }

  // La fecha pertenece al dashboard: aquí se refleja únicamente su texto.
  const dateSource = document.querySelector("#today-label");
  const header = document.querySelector(".main-content > .topbar");
  const date = document.createElement("div");
  date.className = "ldv-header-date";
  date.innerHTML = '<span class="ldv-calendar-icon" aria-hidden="true"></span><div><span>Hoy</span><strong></strong></div>';
  const syncDate = () => {
    date.querySelector("strong").textContent = dateSource?.textContent || "—";
  };
  syncDate();
  header?.append(date);
  const dateObserver = dateSource ? new MutationObserver(syncDate) : null;
  dateObserver?.observe(dateSource, { childList: true, characterData: true, subtree: true });

  let destroyed = false;
  let guideHome = null;
  let guideRow = null;
  const copyEdits = new Map();
  const copy = (selector, text) => {
    const node = view.querySelector(selector);
    if (!node || node.textContent === text) return;
    if (!copyEdits.has(node)) copyEdits.set(node, { original: node.textContent, replacement: text });
    node.textContent = text;
  };

  function decorate() {
    if (destroyed) return;
    for (const node of copyEdits.keys()) if (!node.isConnected) copyEdits.delete(node);
    const advanced = view.querySelector(".bot-advanced");
    if (!advanced) return; // Esperar al montaje/organización del controlador original.
    copy(".bot-config-panel > .panel-header .eyebrow", "Configuración");
    copy(".bot-config-panel > .panel-header h3", "Define la verificación");
    copy(".bot-flow-panel > .panel-header h3", "Seguimiento de ejecución");
    copy(".bot-page-intro .eyebrow", "Automatización Leads Deploy");
    copy(".bot-page-intro .muted", "Automatiza y valida los envíos de leads en UTEL + InConcert de forma rápida y confiable.");
    copy("label:has(#leads-deploy-name) > span", "Nombre de la ejecución");
    copy(".bot-preview > summary", "Ver configuración generada");

    // Mover, nunca clonar: conserva el botón de guía y su listener existente.
    const guide = view.querySelector("#leads-deploy-guide");
    if (guide && !guide.closest(".ldv-guide-row")) {
      guideRow?.remove();
      guideHome = { node: guide, parent: guide.parentNode, next: guide.nextSibling };
      guideRow = document.createElement("div");
      guideRow.className = "ldv-guide-row";
      guideRow.append(guide);
      advanced.append(guideRow);
    }
  }
  decorate();
  // Solo el montaje de la vista: no se observan logs, campos ni resultados.
  const mountObserver = new MutationObserver(decorate);
  mountObserver.observe(view, { childList: true });

  const presentation = {
    view,
    destroy() {
      if (destroyed) return;
      destroyed = true;
      mountObserver.disconnect();
      dateObserver?.disconnect();
      date.remove();
      if (guideHome?.parent.isConnected && guideHome.node.isConnected) {
        const next = guideHome.next?.parentNode === guideHome.parent ? guideHome.next : null;
        guideHome.parent.insertBefore(guideHome.node, next);
      }
      guideRow?.remove();
      for (const [node, edit] of copyEdits) {
        if (node.isConnected && node.textContent === edit.replacement) node.textContent = edit.original;
      }
      copyEdits.clear();
      if (ownsStylesheet) stylesheet.remove();
      if (activePresentation === presentation) activePresentation = null;
    },
  };
  activePresentation = presentation;
  return presentation;
}
