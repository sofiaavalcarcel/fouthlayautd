import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(
  new URL("../src/renderer/bot-module.js", import.meta.url),
  "utf8",
);

test("Nuevos productos ofrece los tres destinos de búsqueda", () => {
  assert.match(source, /id="bot-lead-search-destination"/);
  assert.match(source, /value="inconcert">Solo InConcert/);
  assert.match(source, /value="balanceador">Solo Balanceador/);
  assert.match(source, /value="both">Ambos: InConcert y respaldo en Balanceador/);
});

test("el destino elegido se lee, restaura y parte de Ambos", () => {
  assert.match(source, /lead_search_destination: "both"/);
  assert.match(source, /getInputValue\("#bot-lead-search-destination"\)/);
  assert.match(source, /setInputValue\("#bot-lead-search-destination"/);
});
