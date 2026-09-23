"use strict";

// Adaptación vanilla del comportamiento LiquidButton: añade una capa visual
// de relleno a los botones existentes sin sustituir nodos ni sus listeners.
const BUTTON_SELECTOR = "button:not(.option-wheel__item):not([data-liquid=\"off\"])";

function variantFor(button) {
  if (button.matches(".primary-button")) return "primary";
  if (button.matches(".danger-button")) return "danger";
  if (button.matches(".record-button")) return "record";
  if (button.matches(".nav-item")) return "navigation";
  if (button.matches(".weekly-module-card")) return "card";
  if (button.matches(".text-button")) return "quiet";
  if (button.matches(".icon-button")) return "icon";
  return "secondary";
}

/**
 * Marca botones actuales y futuros con la capa líquida. La observación se
 * limita a nuevos nodos para no interferir con cambios de estado del módulo.
 */
export function initializeLiquidButtons({ root = document.body } = {}) {
  if (!root || root.dataset.liquidButtons === "ready") return null;
  root.dataset.liquidButtons = "ready";

  const decorate = (button) => {
    if (!(button instanceof HTMLButtonElement) || !button.matches(BUTTON_SELECTOR)) return;
    button.classList.add("liquid-button");
    if (!button.dataset.liquidVariant) button.dataset.liquidVariant = variantFor(button);
  };

  const scan = (scope) => {
    if (scope instanceof HTMLButtonElement) decorate(scope);
    scope.querySelectorAll?.("button")?.forEach(decorate);
  };

  scan(root);
  const observer = new MutationObserver((records) => {
    records.forEach((record) => record.addedNodes.forEach((node) => {
      if (node.nodeType === Node.ELEMENT_NODE) scan(node);
    }));
  });
  observer.observe(root, { childList: true, subtree: true });

  return {
    destroy() {
      observer.disconnect();
      root.querySelectorAll(".liquid-button").forEach((button) => {
        button.classList.remove("liquid-button");
        delete button.dataset.liquidVariant;
      });
      delete root.dataset.liquidButtons;
    },
  };
}
