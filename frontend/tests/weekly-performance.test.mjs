import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const moduleScript = fs.readFileSync(new URL("../src/modules/weekly_auto/weekly_performance/module.js", import.meta.url), "utf8");
const apiScript = fs.readFileSync(new URL("../src/services/api.js", import.meta.url), "utf8");
const appScript = fs.readFileSync(new URL("../src/renderer/app.js", import.meta.url), "utf8");

test("Weekly Performance permite cargar, ejecutar, detener y descargar el Excel", () => {
  assert.match(moduleScript, /id="weekly-performance-file"/);
  assert.match(moduleScript, /id="weekly-performance-run"/);
  assert.match(moduleScript, /id="weekly-performance-stop"/);
  assert.match(moduleScript, /id="weekly-performance-download"/);
  assert.match(moduleScript, /Desktop en L y Móvil en M/);
});

test("frontend conserva el contrato multipart de Weekly Performance", () => {
  assert.match(apiScript, /formData\.append\("sheet_name", sheetName\)/);
  assert.match(apiScript, /\/api\/weekly-auto\/performance\/run/);
  assert.match(apiScript, /weeklyPerformanceStatus/);
  assert.match(apiScript, /cancelWeeklyPerformance/);
  assert.match(appScript, /runWeeklyPerformance: api\.runWeeklyPerformance/);
});
