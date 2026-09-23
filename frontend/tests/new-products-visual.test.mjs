import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const directory = new URL("../src/modules/bot_nuevos_productos/", import.meta.url);
const css = await readFile(new URL("visual.css", directory), "utf8");
const js = await readFile(new URL("visual.js", directory), "utf8");
const bootstrap = await readFile(new URL("../src/renderer/gooey-buttons.js", import.meta.url), "utf8");

// Inspección de reglas sin dependencias. Se ignoran llaves dentro de cadenas.
function rules(source) {
  source = source.replace(/\/\*[\s\S]*?\*\//g, "");
  const result = [];
  let cursor = 0;
  while (cursor < source.length) {
    const open = source.indexOf("{", cursor);
    if (open < 0) break;
    const selector = source.slice(cursor, open).trim();
    let depth = 1, quote = "", index = open + 1;
    for (; index < source.length && depth; index++) {
      const ch = source[index];
      if (quote) {
        if (ch === "\\") index++;
        else if (ch === quote) quote = "";
      } else if (ch === '"' || ch === "'") quote = ch;
      else if (ch === "{") depth++;
      else if (ch === "}") depth--;
    }
    assert.equal(depth, 0, "Regla CSS sin cerrar");
    const body = source.slice(open + 1, index - 1);
    if (selector.startsWith("@media")) result.push(...rules(body));
    else result.push({ selector, body });
    cursor = index;
  }
  return result;
}
function splitSelectors(value) {
  let depth = 0, start = 0;
  const list = [];
  for (let i = 0; i < value.length; i++) {
    if (value[i] === "(") depth++;
    if (value[i] === ")") depth--;
    if (value[i] === "," && depth === 0) { list.push(value.slice(start, i).trim()); start = i + 1; }
  }
  list.push(value.slice(start).trim());
  return list;
}

test("todas las reglas visuales están aisladas a Nuevos productos", () => {
  const parsed = rules(css);
  assert.ok(parsed.length > 100);
  for (const {selector, body} of parsed) {
    for (const item of splitSelectors(selector)) {
      assert.ok(item.startsWith("#view-bot") || item.startsWith("body:has(#view-bot.active)") || item === ".np-header-date", `Regla global: ${item}`);
      if (item === ".np-header-date") assert.match(body, /^\s*display:\s*none;?\s*$/);
    }
  }
});
test("los estados hidden originales tienen prioridad sobre el estilo de botones", () => {
  assert.match(css, /#view-bot \[hidden\]\s*\{\s*display:\s*none\s*!important/);
  assert.match(css, /#view-bot button:disabled/);
  assert.match(css, /#view-bot button:focus-visible/);
});
test("la presentación no envía datos ni modifica configuración o controles", () => {
  assert.doesNotMatch(js, /\b(fetch|XMLHttpRequest|WebSocket|localStorage|sessionStorage)\b/);
  assert.doesNotMatch(js, /\.(value|checked|disabled|hidden)\s*=/);
  assert.doesNotMatch(js, /dispatchEvent|\.click\(|\.submit\(|requestSubmit/);
  assert.doesNotMatch(js, /setInterval|setTimeout|services\/api|backend\//);
});
test("la guía conserva su nodo y la fecha no duplica el ID original", () => {
  assert.match(js, /guideRow\.append\(guide\)/);
  assert.match(js, /guideHome\.parent\.insertBefore\(guideHome\.node, next\)/);
  assert.doesNotMatch(js, /cloneNode|id\s*=\s*['"]today-label/);
  assert.match(js, /dateSource\?\.textContent/);
});
test("montaje idempotente y limpieza de observadores", () => {
  assert.match(js, /if \(activePresentation\) return activePresentation/);
  assert.match(js, /if \(destroyed\) return/);
  assert.match(js, /mountObserver\.disconnect\(\)/);
  assert.match(js, /dateObserver\?\.disconnect\(\)/);
  assert.match(js, /activePresentation = null/);
});
test("el tema no bloquea el arranque y conserva planeta y robot", () => {
  assert.match(bootstrap, /import\("\.\.\/modules\/bot_nuevos_productos\/visual\.js\?v=reference-1"\)/);
  assert.match(bootstrap, /\.catch\(\(error\) => console\.warn/);
  assert.match(bootstrap, /initializeDashboardGlobe\(\)/);
  assert.match(bootstrap, /initializeDashboardRobot\(\)/);
});
test("hay adaptación móvil, telemetría desplazable y movimiento reducido", () => {
  assert.match(css, /@media \(max-width: 700px\)/);
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(css, /grid-template-areas: "config" "flow" "diagnostic"/);
  assert.match(css, /#view-bot \.bot-terminal[^}]+overflow: auto/);
});
