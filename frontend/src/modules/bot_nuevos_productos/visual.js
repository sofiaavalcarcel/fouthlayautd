/** Presentación de Nuevos productos. No lee ni modifica la configuración del bot. */
const STYLE_ID = "new-products-visual-style";
let activePresentation = null;

export function initializeNewProductsVisuals() {
  if (activePresentation) return activePresentation;
  const view = document.querySelector("#view-bot");
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

  // Copia solo el texto de la fecha existente. El ID original y su actualización
  // continúan perteneciendo al dashboard. No se crean consultas ni temporizadores.
  const dateSource = document.querySelector("#today-label");
  const header = document.querySelector(".main-content > .topbar");
  const date = document.createElement("div");
  date.className = "np-header-date";
  date.innerHTML = '<span class="np-calendar-icon" aria-hidden="true"></span><div><span>Hoy</span><strong></strong></div>';
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
    if (!copyEdits.has(node)) copyEdits.set(node, node.textContent);
    node.textContent = text;
  };
  function decorate() {
    for (const node of copyEdits.keys()) if (!node.isConnected) copyEdits.delete(node);
    const advanced = view.querySelector(".bot-advanced");
    if (!advanced) return; // La lógica original termina de montar/organizar los controles.
    copy(".bot-config-panel > .panel-header .eyebrow", "Configuración");
    copy(".bot-config-panel > .panel-header h3", "Define la verificación");
    copy(".bot-flow-panel > .panel-header h3", "Seguimiento de ejecución");
    copy(".bot-page-intro .eyebrow", "Automatización UTEL");
    copy(".bot-page-intro .muted", "Automatiza y valida los envíos de leads en UTEL + InConcert de forma rápida y confiable.");
    copy("label:has(#bot-name) > span", "Nombre de la ejecución");
    copy("label:has(#bot-country) > span", "País *");
    copy(".bot-preview > summary", "Ver configuración generada");

    // Conserva el MISMO botón y su listener: la guía pasa al panel avanzado,
    // en lugar de perderse al retirar la tarjeta hero redundante de la referencia.
    const guide = view.querySelector("#bot-guide");
    if (guide && !guide.closest(".np-guide-row")) {
      guideHome = { node: guide, parent: guide.parentNode, next: guide.nextSibling };
      guideRow = document.createElement("div");
      guideRow.className = "np-guide-row";
      guideRow.append(guide);
      advanced.append(guideRow);
    }
  }
  decorate();
  // Solo observa el montaje del módulo, NO sus logs ni las actualizaciones del bot.
  const mountObserver = new MutationObserver(decorate);
  mountObserver.observe(view, { childList: true });

  activePresentation = {
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
      for (const [node, text] of copyEdits) if (node.isConnected) node.textContent = text;
      copyEdits.clear();
      if (ownsStylesheet) stylesheet.remove();
      activePresentation = null;
    },
  };
  return activePresentation;
}
