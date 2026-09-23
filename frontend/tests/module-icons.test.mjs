import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const html = fs.readFileSync(new URL("../index.html", import.meta.url), "utf8");
const iconsDirectory = new URL("../src/renderer/assets/module-icons/", import.meta.url);

// La navegación visible debe conservar un recurso de diseño para cada módulo.
const moduleIcons = {
  dashboard: "dashboard.png",
  bot: "bot-nuevos-productos.png",
  "leads-deploy": "bot-leads-deploy.png",
  "weekly-leads": "form-validation.png",
  "weekly-auto": "weekly-auto.png",
  "weekly-photos": "weekly-photos.png",
  "weekly-forms": "weekly-forms.png",
  "weekly-performance": "weekly-performance.png",
  history: "history.png",
  settings: "settings.png",
};

test("cada módulo de navegación usa su icono entregado", () => {
  for (const [view, filename] of Object.entries(moduleIcons)) {
    const path = `./src/renderer/assets/module-icons/${filename}`;
    assert.match(html, new RegExp(`data-view="${view}"[\\s\\S]*?${path.replaceAll("/", "\\/")}`));
    assert.ok(fs.existsSync(new URL(filename, iconsDirectory)), `Falta el recurso ${filename}`);
  }
});

test("los iconos se presentan como imágenes decorativas accesibles", () => {
  const imageTags = [...html.matchAll(/<img class="(?:nav-icon-image|nav-subitem-icon)"[^>]+>/g)].map(([tag]) => tag);
  assert.equal(imageTags.length, 10);
  for (const tag of imageTags) {
    assert.match(tag, /alt=""/);
    assert.match(tag, /aria-hidden="true"/);
  }
});
