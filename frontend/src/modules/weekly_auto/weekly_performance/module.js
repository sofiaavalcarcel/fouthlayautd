"use strict";

const state = { file: null, jobId: null, pollTimer: null };

function escapeHtml(value) {
  return String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
}

function mount() {
  const view = document.querySelector("#view-weekly-performance");
  if (!view || document.querySelector("#weekly-performance-panel")) return;
  view.insertAdjacentHTML("beforeend", `
    <article class="panel" id="weekly-performance-panel" style="margin-top:18px;">
      <div class="panel-header">
        <div>
          <p class="eyebrow accent">Weekly Performance</p>
          <h3>Medición PageSpeed desde Excel</h3>
          <p class="panel-subtitle">Lee las URLs de la columna D y escribe Desktop en L y Móvil en M. Guarda avances cada 10 resultados.</p>
        </div>
        <span class="status-badge success">PAGESPEED INSIGHTS</span>
      </div>
      <div class="bot-fields">
        <label class="pdp-file-field full"><span>Excel de Weekly Performance (.xlsx)</span>
          <input id="weekly-performance-file" type="file" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" />
          <small id="weekly-performance-file-name">Selecciona el archivo que contiene las URLs.</small>
        </label>
        <label class="field"><span>Pestaña del Excel</span>
          <input id="weekly-performance-sheet" type="text" value="Hoja 1" maxlength="120" />
        </label>
        <label class="field"><span>Procesos simultáneos</span>
          <input id="weekly-performance-workers" type="number" min="1" max="16" value="8" />
          <small>PageSpeed puede limitar solicitudes muy frecuentes.</small>
        </label>
      </div>
      <div class="bot-flow-actions" style="margin-top:12px;">
        <div><button class="secondary-button" id="weekly-performance-download" type="button" hidden>Descargar Excel actualizado</button></div>
        <div><button class="danger-button" id="weekly-performance-stop" type="button" hidden>Detener</button>
          <button class="primary-button" id="weekly-performance-run" type="button" disabled>Ejecutar Weekly Performance <span>→</span></button></div>
      </div>
      <div class="bot-run-status" id="weekly-performance-status">Selecciona un Excel para comenzar.</div>
      <pre class="bot-terminal" id="weekly-performance-terminal" aria-live="polite">[SISTEMA] Esperando Excel con URLs en la columna D.</pre>
      <div id="weekly-performance-summary" class="pdp-summary" style="margin-top:12px;display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px;"></div>
    </article>`);
}

function setTerminal(lines) {
  const terminal = document.querySelector("#weekly-performance-terminal");
  if (!terminal) return;
  terminal.textContent = lines.filter(Boolean).join("\n");
  terminal.scrollTop = terminal.scrollHeight;
}

function renderJob(job) {
  const status = document.querySelector("#weekly-performance-status");
  const summary = document.querySelector("#weekly-performance-summary");
  const download = document.querySelector("#weekly-performance-download");
  if (!status || !summary) return;
  const running = ["QUEUED", "RUNNING"].includes(job.status);
  const successful = job.status === "PASS";
  status.className = `bot-run-status ${running ? "running" : successful ? "success" : job.status === "FAIL" ? "error" : ""}`;
  status.innerHTML = `<strong>${escapeHtml(job.status)}</strong><span>${escapeHtml(job.summary || "")}</span>`;
  summary.innerHTML = [
    ["Procesadas", `${job.completed || 0}/${job.total || 0}`],
    ["Completas", job.successful || 0],
    ["Con error", job.failed || 0],
    ["Fila actual", job.current_row || "—"],
    ["Desktop", job.current_desktop ?? "—"],
    ["Móvil", job.current_mobile ?? "—"],
  ].map(([label, value]) => `<div class="bot-summary-card"><strong>${escapeHtml(value)}</strong><span>${label}</span></div>`).join("");
  setTerminal([
    `[${job.status}] ${job.completed || 0}/${job.total || 0} URLs procesadas`,
    job.current_row ? `[FILA] ${job.current_row} · Desktop ${job.current_desktop ?? "—"} · Móvil ${job.current_mobile ?? "—"}` : "",
    job.current_url ? `[URL] ${job.current_url}` : "",
    job.last_error ? `[DETALLE] ${job.last_error}` : "",
  ]);
  if (download) download.hidden = !job.download_url;
}

function finishWatching(dependencies, job) {
  window.clearInterval(state.pollTimer);
  state.pollTimer = null;
  document.querySelector("#weekly-performance-stop").hidden = true;
  document.querySelector("#weekly-performance-run").disabled = !state.file;
  const ok = job.status === "PASS";
  dependencies.showToast(ok ? "Weekly Performance finalizó." : (job.summary || `Weekly Performance terminó: ${job.status}`), ok ? "info" : "error");
}

async function watch(dependencies) {
  let stillRunning = true;
  const poll = async () => {
    try {
      const job = await dependencies.weeklyPerformanceStatus(state.jobId);
      renderJob(job);
      if (!["QUEUED", "RUNNING"].includes(job.status)) {
        stillRunning = false;
        finishWatching(dependencies, job);
      }
    } catch (error) {
      window.clearInterval(state.pollTimer);
      state.pollTimer = null;
      document.querySelector("#weekly-performance-run").disabled = !state.file;
      dependencies.showToast(`No se pudo consultar Weekly Performance: ${error.message}`, "error");
    }
  };
  await poll();
  if (stillRunning && state.jobId && !state.pollTimer) state.pollTimer = window.setInterval(poll, 1800);
}

function setup(dependencies) {
  const fileInput = document.querySelector("#weekly-performance-file");
  const run = document.querySelector("#weekly-performance-run");
  const stop = document.querySelector("#weekly-performance-stop");
  const download = document.querySelector("#weekly-performance-download");

  fileInput.addEventListener("change", () => {
    state.file = fileInput.files?.[0] || null;
    run.disabled = !state.file;
    download.hidden = true;
    document.querySelector("#weekly-performance-file-name").textContent = state.file?.name || "Selecciona el archivo que contiene las URLs.";
    setTerminal(state.file ? [`[ARCHIVO] ${state.file.name}`, "[LISTO] Se validará la pestaña y la columna D al ejecutar."] : ["[SISTEMA] Esperando Excel con URLs en la columna D."]);
  });

  run.addEventListener("click", async () => {
    if (!state.file) return;
    const sheetName = document.querySelector("#weekly-performance-sheet").value.trim();
    const maxWorkers = Number(document.querySelector("#weekly-performance-workers").value);
    if (!sheetName) return dependencies.showToast("Indica la pestaña que contiene las URLs.", "error");
    if (!Number.isInteger(maxWorkers) || maxWorkers < 1 || maxWorkers > 16) return dependencies.showToast("Los procesos simultáneos deben estar entre 1 y 16.", "error");
    run.disabled = true;
    stop.hidden = false;
    download.hidden = true;
    setTerminal(["[SISTEMA] Validando Excel e iniciando PageSpeed Insights…"]);
    try {
      const job = await dependencies.runWeeklyPerformance(state.file, sheetName, maxWorkers);
      state.jobId = job.job_id;
      renderJob(job);
      await watch(dependencies);
    } catch (error) {
      run.disabled = false;
      stop.hidden = true;
      dependencies.showToast(error.message, "error");
    }
  });

  stop.addEventListener("click", async () => {
    if (!state.jobId) return;
    stop.disabled = true;
    try {
      const job = await dependencies.cancelWeeklyPerformance(state.jobId);
      renderJob(job);
      dependencies.showToast("Detención solicitada; se guardará el avance disponible.", "info");
    } catch (error) {
      dependencies.showToast(error.message, "error");
    } finally {
      stop.disabled = false;
    }
  });

  download.addEventListener("click", () => {
    if (!state.jobId) return;
    const anchor = document.createElement("a");
    anchor.href = dependencies.weeklyPerformanceDownloadUrl(state.jobId);
    anchor.download = "weekly-performance-resultados.xlsx";
    anchor.click();
  });
}

export function initializeWeeklyPerformanceModule(dependencies) {
  mount();
  setup(dependencies);
}
