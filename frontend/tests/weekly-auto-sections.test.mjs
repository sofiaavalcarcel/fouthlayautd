import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const html = fs.readFileSync(new URL("../index.html", import.meta.url), "utf8");
const shellScript = fs.readFileSync(new URL("../src/modules/weekly_auto/module.js", import.meta.url), "utf8");
const photosScript = fs.readFileSync(new URL("../src/modules/weekly_auto/weekly_photos/module.js", import.meta.url), "utf8");
const rendererAdapter = fs.readFileSync(new URL("../src/renderer/weekly-auto-module.js", import.meta.url), "utf8");

test("cada automatización tiene una subcarpeta de código independiente", () => {
  for (const section of ["weekly_photos", "weekly_forms", "weekly_leads", "weekly_performance"]) {
    assert.ok(fs.existsSync(new URL(`../src/modules/weekly_auto/${section}/module.js`, import.meta.url)));
  }
  assert.match(shellScript, /\.\/weekly_photos\/module\.js/);
  assert.match(shellScript, /\.\/weekly_forms\/module\.js/);
  assert.match(shellScript, /\.\/weekly_leads\/module\.js/);
  assert.match(shellScript, /\.\/weekly_performance\/module\.js/);
});

test("la automatización existente vive en Weekly Photos", () => {
  assert.match(photosScript, /initializeWeeklyPhotosModule/);
  assert.match(photosScript, /runWeeklyAuto/);
  assert.match(photosScript, /weeklyAutoStatus/);
  assert.match(photosScript, /cancelWeeklyAuto/);
});

test("el adaptador mantiene el import histórico de la aplicación", () => {
  assert.match(rendererAdapter, /\.\.\/modules\/weekly_auto\/module\.js/);
  assert.match(html, /id="weekly-auto-run"/);
  assert.match(html, /id="weekly-auto-results"/);
  assert.doesNotMatch(html, /data-weekly-section=/);
});
