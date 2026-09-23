"use strict";

// Adaptación ligera del componente OptionWheel de React Bits para la app
// vanilla de UTEL. Trabaja sobre copias visuales de los botones existentes,
// así las rutas y listeners originales permanecen intactos.
const DEFAULT_OPTIONS = {
  side: "left",
  rowHeight: 43,
  curve: 0.55,
  tilt: 4.5,
  blur: 0.35,
  fade: 0.13,
  minOpacity: 0.26,
  smoothing: 180,
  loop: false,
  draggable: true,
};

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function normalizeIndex(value, count, loop) {
  if (!count) return 0;
  if (loop) return ((value % count) + count) % count;
  return clamp(value, 0, count - 1);
}

/**
 * Monta el wheel visual para un conjunto de botones ya enlazados por la app.
 * El callback opcional se ejecuta solo cuando el usuario confirma una opción.
 */
export function initializeOptionWheel({ navigation, sourceItems, onChange, options = {} } = {}) {
  if (!navigation || !sourceItems?.length || navigation.querySelector(".option-wheel")) return null;

  const cfg = { ...DEFAULT_OPTIONS, ...options };
  const sources = sourceItems.filter((item) => item instanceof HTMLElement);
  if (!sources.length) return null;

  const root = document.createElement("div");
  root.className = `option-wheel option-wheel--sidebar${cfg.side === "right" ? " option-wheel--right" : ""}`;
  root.setAttribute("role", "listbox");
  root.setAttribute("aria-label", "Módulos de navegación");
  root.tabIndex = 0;
  root.style.setProperty("--ow-row-height", `${cfg.rowHeight}px`);
  root.style.setProperty("--ow-inset", "10px");
  navigation.appendChild(root);
  navigation.classList.add("option-wheel-active");

  // Se clona únicamente la capa visual: cada copia sigue delegando la acción
  // en su botón original para conservar navegación, ARIA y contratos actuales.
  const items = sources.map((source, index) => {
    const item = source.cloneNode(true);
    item.classList.remove("active", "expanded");
    item.classList.add("option-wheel__item");
    item.setAttribute("role", "option");
    item.setAttribute("aria-selected", "false");
    item.dataset.optionWheelIndex = String(index);
    item.addEventListener("click", (event) => {
      event.preventDefault();
      if (dragMoved) return;
      commitIndex(index);
      // El integrador puede reaccionar mediante onChange. Si no lo necesita,
      // mantenemos el comportamiento autónomo de activar el botón original.
      if (!onChange) source.click();
    });
    root.appendChild(item);
    return item;
  });

  let position = 0;
  let target = 0;
  let selectedIndex = 0;
  let frameId = null;
  let lastFrame = 0;
  let wheelTimer = null;
  let drag = null;
  let dragMoved = false;
  let destroyed = false;

  // Ajusta la separación al espacio real disponible: la rueda crece con el
  // sidebar, pero mantiene límites para que las opciones no se dispersen ni
  // queden amontonadas en ventanas de menor altura.
  const getRowHeight = () => {
    const availableHeight = root.clientHeight || cfg.rowHeight * items.length;
    return clamp(availableHeight / Math.max(items.length + 2, 1), cfg.rowHeight * 0.82, cfg.rowHeight * 1.4);
  };

  // Distribuye cada opción sobre un arco con suavizado independiente del FPS.
  const runFrame = (now) => {
    if (destroyed) return;
    const delta = Math.min(Math.max((now - lastFrame) / 1000, 0), 0.05);
    lastFrame = now;
    const tau = Math.max(cfg.smoothing, 1) / 1000;
    const easing = 1 - Math.exp(-delta / tau);
    let next = position + (target - position) * easing;
    const settled = Math.abs(target - next) < 0.001;
    if (settled) next = target;
    position = next;

    const mirror = cfg.side === "right" ? -1 : 1;
    const tiltRad = (cfg.tilt * Math.PI) / 180;
    const rowHeight = getRowHeight();
    const radius = tiltRad > 0.0005 ? rowHeight / tiltRad : 0;
    root.style.setProperty("--ow-row-height", `${rowHeight.toFixed(2)}px`);
    items.forEach((item, index) => {
      let distance = index - next;
      if (cfg.loop && items.length > 1) {
        distance = ((distance % items.length) + items.length) % items.length;
        if (distance > items.length / 2) distance -= items.length;
      }
      const absoluteDistance = Math.abs(distance);
      const angle = radius
        ? clamp(distance * tiltRad, -Math.PI / 2, Math.PI / 2)
        : 0;
      const x = radius ? -mirror * radius * (1 - Math.cos(angle)) * cfg.curve : 0;
      const y = radius ? radius * Math.sin(angle) : distance * rowHeight;
      const rotation = (mirror * angle * 180) / Math.PI;
      item.style.transform = `translate(${x.toFixed(2)}px, calc(${y.toFixed(2)}px - 50%)) rotate(${rotation.toFixed(3)}deg)`;
      item.style.opacity = String(Math.max(cfg.minOpacity, 1 - absoluteDistance * cfg.fade));
      item.style.filter = cfg.blur > 0 ? `blur(${(absoluteDistance * cfg.blur).toFixed(2)}px)` : "none";
      item.style.setProperty("--ow-p", Math.max(0, 1 - Math.min(absoluteDistance, 1)).toFixed(4));
    });

    frameId = settled ? null : requestAnimationFrame(runFrame);
  };

  const startFrame = () => {
    if (frameId != null) cancelAnimationFrame(frameId);
    lastFrame = performance.now();
    frameId = requestAnimationFrame(runFrame);
  };

  const setSelectedVisual = (index) => {
    selectedIndex = normalizeIndex(index, items.length, cfg.loop);
    items.forEach((item, itemIndex) => {
      const selected = itemIndex === selectedIndex;
      item.classList.toggle("option-wheel__item--selected", selected);
      item.classList.toggle("active", selected);
      item.classList.toggle("expanded", selected && sources[itemIndex].classList.contains("expanded"));
      item.setAttribute("aria-selected", String(selected));
    });
  };

  const setTarget = (value, { snap = false } = {}) => {
    let next = cfg.loop ? value : clamp(value, 0, items.length - 1);
    if (snap) next = Math.round(next);
    target = next;
    setSelectedVisual(Math.round(next));
    startFrame();
  };

  const commitIndex = (index) => {
    const nextIndex = normalizeIndex(index, items.length, cfg.loop);
    setTarget(nextIndex, { snap: true });
    onChange?.(nextIndex, sources[nextIndex]);
  };

  const syncFromSources = () => {
    // Si padre y submódulo están activos al mismo tiempo, el submódulo aparece
    // después en el DOM y se toma como la opción visual más específica.
    let active = -1;
    sources.forEach((source, index) => {
      if (source.classList.contains("active")) active = index;
    });
    if (active >= 0) setTarget(active, { snap: true });
    else startFrame();
  };

  const onWheel = (event) => {
    event.preventDefault();
    const delta = event.deltaMode === 1 ? event.deltaY * 24 : event.deltaY;
    const step = clamp(delta / getRowHeight(), -1, 1);
    setTarget(target + step);
    if (wheelTimer) clearTimeout(wheelTimer);
    wheelTimer = setTimeout(() => commitIndex(Math.round(target)), 140);
  };

  const onPointerDown = (event) => {
    if (!cfg.draggable) return;
    drag = { y: event.clientY, start: target, pointerId: event.pointerId };
    dragMoved = false;
  };

  const onPointerMove = (event) => {
    if (!drag) return;
    const distance = event.clientY - drag.y;
    if (!dragMoved && Math.abs(distance) > 4) {
      dragMoved = true;
      root.setPointerCapture?.(drag.pointerId);
    }
    if (dragMoved) setTarget(drag.start - distance / getRowHeight());
  };

  const onPointerEnd = () => {
    if (!drag) return;
    drag = null;
    if (dragMoved) commitIndex(Math.round(target));
    dragMoved = false;
  };

  const onKeyDown = (event) => {
    if (!["ArrowUp", "ArrowLeft", "ArrowDown", "ArrowRight"].includes(event.key)) return;
    event.preventDefault();
    const direction = event.key === "ArrowUp" || event.key === "ArrowLeft" ? -1 : 1;
    commitIndex(Math.round(target) + direction);
  };

  root.addEventListener("wheel", onWheel, { passive: false });
  root.addEventListener("pointerdown", onPointerDown);
  root.addEventListener("pointermove", onPointerMove);
  root.addEventListener("pointerup", onPointerEnd);
  root.addEventListener("pointercancel", onPointerEnd);
  root.addEventListener("keydown", onKeyDown);

  // Recalcula el arco cuando cambia la altura del viewport sin alterar la
  // opción activa ni disparar una navegación adicional.
  const onResize = () => startFrame();
  window.addEventListener("resize", onResize);

  const observer = new MutationObserver(syncFromSources);
  // Observa solo los botones originales para no reaccionar a los cambios de
  // clase/ARIA que el propio wheel aplica sobre sus copias visuales.
  sources.forEach((source) => observer.observe(source, { attributes: true, attributeFilter: ["class", "aria-expanded"] }));
  syncFromSources();

  return {
    root,
    destroy() {
      destroyed = true;
      if (frameId != null) cancelAnimationFrame(frameId);
      if (wheelTimer) clearTimeout(wheelTimer);
      observer.disconnect();
      root.removeEventListener("wheel", onWheel);
      root.removeEventListener("pointerdown", onPointerDown);
      root.removeEventListener("pointermove", onPointerMove);
      root.removeEventListener("pointerup", onPointerEnd);
      root.removeEventListener("pointercancel", onPointerEnd);
      root.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("resize", onResize);
      root.remove();
      navigation.classList.remove("option-wheel-active");
    },
  };
}
