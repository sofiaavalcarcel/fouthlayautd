import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const moduleScript = fs.readFileSync(new URL("../src/modules/weekly_auto/weekly_leads/module.js", import.meta.url), "utf8");
const sharedScript = fs.readFileSync(new URL("../src/modules/weekly_auto/lead_submission/module.js", import.meta.url), "utf8");
const apiScript = fs.readFileSync(new URL("../src/services/api.js", import.meta.url), "utf8");

test("Weekly Leads tiene identidad y controles independientes", () => {
  assert.match(moduleScript, /initializeWeeklyLeadsModule/);
  assert.match(moduleScript, /weekly_leads/);
  assert.match(moduleScript, /weekly-leads/);
  assert.match(sharedScript, /5 filas y descansa 60 segundos/);
});

test("Weekly Leads analiza su matriz y usa el lote existente de envíos", () => {
  assert.match(apiScript, /\/api\/weekly-auto\/leads\/spreadsheet-preview/);
  assert.match(apiScript, /runWeeklyLeadsBatch/);
  assert.match(apiScript, /automation_module: "weekly_leads"/);
  assert.match(apiScript, /\/api\/weekly-auto\/leads\/run/);
});

test("Form Validation acepta URLs manuales y conserva la búsqueda dual configurable", () => {
  assert.match(sharedScript, /allowManualUrls/);
  assert.match(sharedScript, /URLs de landings QA/);
  assert.match(sharedScript, /parallel_crm_search: true/);
  assert.match(apiScript, /\/api\/form-validation\/urls\/preview/);
  assert.match(apiScript, /\/api\/form-validation\/urls\/run/);
  assert.match(sharedScript, /Solo llenar, no enviar/);
  assert.match(sharedScript, /fill_only: Boolean\(element\("fill-only"\)\?\.checked\)/);
});
