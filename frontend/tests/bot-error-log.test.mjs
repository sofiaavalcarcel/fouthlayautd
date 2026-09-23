import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

// El renderer usa módulos ESM aunque Electron main es CommonJS.
const source = await readFile(new URL("../src/modules/bot_nuevos_productos/module.js", import.meta.url), "utf8");
const { buildErrorLog, isSafeUtelRetry } = await import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);

test("el log contiene solo errores con la fila y el mensaje completo", () => {
  const message = `Timeout\n${"detalle ".repeat(200)}`;
  const log = buildErrorLog({ results: [
    { row: { row_number: 2 }, result: { stages: [{ status: "PASS", message: "NO INCLUIR" }] } },
    { row: { row_number: 5, level: "Licenciatura Ejecutiva" }, result: { status: "FAIL", dry_run: true, stages: [{ status: "FAIL", stage: "utel_fill", message, selector: "#program", screenshot: "error.png" }] } },
  ] });
  assert.ok(log.includes("Fila: 5"));
  assert.ok(log.includes(message));
  assert.ok(log.includes("#program"));
  assert.ok(log.includes("error.png"));
  assert.ok(log.includes("DRY RUN - SIN ENVÍO"));
  assert.ok(!log.includes("NO INCLUIR"));
});

test("los errores del lote también se pueden compartir", () => {
  assert.ok(buildErrorLog({ status: "FAIL", summary: "Error al leer Excel" }).includes("Error al leer Excel"));
  assert.equal(buildErrorLog({ results: [] }), "");
});

test("el log omite bloqueos recuperados y checkpoints todavía activos", () => {
  const log = buildErrorLog({
    status: "RUNNING",
    failed: 0,
    results: [
      {
        row: { row_number: 2, level: "Maestría" },
        result: {
          status: "PASS",
          stages: [{ status: "FAIL", stage: "lead_balancer_search", message: "Cloudflare" }],
        },
      },
      {
        row: { row_number: 3, level: "Doctorado" },
        result: {
          status: "FAIL",
          utel_submission: "pending",
          utel_submission_attempted: null,
          summary: "Ejecución iniciada y estado final aún desconocido.",
          stages: [],
        },
      },
    ],
  });

  assert.equal(log, "");
});

test("solo se reintentan fallos ocurridos antes del clic", () => {
  assert.equal(isSafeUtelRetry({ result: { status: "FAIL", utel_submission_attempted: false } }), true);
  assert.equal(isSafeUtelRetry({ result: { status: "FAIL", utel_submission_attempted: true } }), false);
  assert.equal(isSafeUtelRetry({ result: { status: "FAIL" } }), false);
  assert.equal(isSafeUtelRetry({ result: { status: "PASS", utel_submission_attempted: false } }), false);
});
