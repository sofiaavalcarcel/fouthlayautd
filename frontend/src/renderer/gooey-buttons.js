"use strict";

import { initializeDashboardGlobe } from "./dashboard-globe.js?v=hollow-arcs-4";
import { initializeDashboardRobot } from "./dashboard-robot.js?v=robot-3d-1";

// Adaptación sin dependencias del efecto GooeyNav de React Bits.
// La delegación conserva los listeners, IDs y estados de todos los botones existentes y futuros.
const BUTTON_SELECTOR = "button, input[type='button'], input[type='submit'], input[type='file']";
const BURST_DURATION_MS = 280;
const CLEANUP_DELAY_MS = 420;
const lastBurstByButton = new WeakMap();

const palettes = {
  cyan: ["#12e7ef", "#16e6c0", "#67d7ff"],
  primary: ["#12e7ef", "#16e6c0", "#8f7cff", "#67d7ff"],
  danger: ["#ff3d8d", "#ff718f", "#ffc2d6"],
};

function paletteFor(button) {
  if (button.matches(".danger-button, .record-button")) return palettes.danger;
  if (button.matches(".primary-button")) return palettes.primary;
  return palettes.cyan;
}

function getLayer() {
  let layer = document.querySelector("#gooey-button-layer");
  if (layer) return layer;
  layer = document.createElement("div");
  layer.id = "gooey-button-layer";
  layer.className = "gooey-button-layer";
  layer.setAttribute("aria-hidden", "true");
  document.body.appendChild(layer);
  return layer;
}

function clickOrigin(event, rect) {
  const pointerClick = event.detail > 0 && Number.isFinite(event.clientX) && Number.isFinite(event.clientY);
  return pointerClick
    ? { x: event.clientX, y: event.clientY }
    : { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
}

function createParticle(index, count, distance, colors) {
  const angle = (Math.PI * 2 * index) / count + (Math.random() - 0.5) * 0.34;
  const travel = distance * (0.76 + Math.random() * 0.34);
  const particle = document.createElement("span");
  particle.className = "gooey-button-particle";
  particle.style.setProperty("--gooey-x", `${Math.cos(angle) * travel}px`);
  particle.style.setProperty("--gooey-y", `${Math.sin(angle) * travel}px`);
  particle.style.setProperty("--gooey-rotate", `${Math.round((Math.random() - 0.5) * 150)}deg`);
  particle.style.setProperty("--gooey-scale", `${(0.78 + Math.random() * 0.5).toFixed(2)}`);
  particle.style.setProperty("--gooey-delay", `${index * 7}ms`);
  particle.style.setProperty("--gooey-color", colors[index % colors.length]);
  return particle;
}

function makeBurst(button, event, reducedMotion) {
  const rect = button.getBoundingClientRect();
  if (!rect.width || !rect.height) return;

  const origin = clickOrigin(event, rect);
  const colors = paletteFor(button);
  const burst = document.createElement("span");
  burst.className = `gooey-button-burst${reducedMotion ? " reduced-motion" : ""}`;
  burst.style.left = `${origin.x}px`;
  burst.style.top = `${origin.y}px`;
  burst.style.setProperty("--gooey-width", `${rect.width}px`);
  burst.style.setProperty("--gooey-height", `${rect.height}px`);
  burst.style.setProperty("--gooey-duration", `${BURST_DURATION_MS}ms`);
  burst.style.setProperty("--gooey-primary", colors[0]);
  burst.appendChild(document.createElement("span")).className = "gooey-button-flash";

  if (!reducedMotion) {
    const compact = rect.width < 48 || rect.height < 30;
    const count = compact ? 5 : button.matches(".primary-button") ? 9 : 7;
    const distance = Math.min(34, Math.max(19, Math.min(rect.width, rect.height) * 0.82));
    for (let index = 0; index < count; index += 1) {
      burst.appendChild(createParticle(index, count, distance, colors));
    }
  }

  getLayer().appendChild(burst);
  requestAnimationFrame(() => burst.classList.add("active"));
  window.setTimeout(() => burst.remove(), CLEANUP_DELAY_MS);
}

export function initializeGooeyButtons() {
  initializeDashboardGlobe();
  initializeDashboardRobot();

  if (document.documentElement.dataset.gooeyButtons === "ready") return;
  document.documentElement.dataset.gooeyButtons = "ready";
  // Carga visual aislada: un fallo del tema no bloquea los módulos funcionales.
  import("../modules/bot_nuevos_productos/visual.js?v=reference-1")
    .then(({ initializeNewProductsVisuals }) => initializeNewProductsVisuals())
    .catch((error) => console.warn("No se pudo cargar el tema de Nuevos productos.", error));

  // Tema independiente de Leads Deploy; no cambia su controlador ni sus llamadas API.
  import("../modules/bot_leads_deploy/visual.js?v=reference-1")
    .then(({ initializeLeadsDeployVisuals }) => initializeLeadsDeployVisuals())
    .catch((error) => console.warn("No se pudo cargar el tema de Leads Deploy.", error));

  const reducedMotionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");

  document.addEventListener("click", (event) => {
    const button = event.target.closest?.(BUTTON_SELECTOR);
    if (!button || button.disabled || button.hidden || button.dataset.gooey === "off") return;

    const now = performance.now();
    if (now - (lastBurstByButton.get(button) || 0) < 120) return;
    lastBurstByButton.set(button, now);
    makeBurst(button, event, reducedMotionQuery.matches);
  }, true);
}
