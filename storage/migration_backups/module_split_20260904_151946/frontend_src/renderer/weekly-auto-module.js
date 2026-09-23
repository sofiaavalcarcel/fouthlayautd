"use strict";

// Controlador de Weekly Auto: configuración, sondeo de estado y resultados por URL.
const CONFIG_KEY = "qa-automation.weekly-auto-config";
const JOB_KEY = "qa-automation.weekly-auto-active-job";
const LAST_JOB_KEY = "qa-automation.weekly-auto-last-job";

const state = {
  jobId: null,
  pollTimer: null,
};

const DEFAULT_CONFIG = {
  name: "Weekly Auto",
  urls: [],
  use_default_urls: true,
  browser: "chromium",
  headless: true,
  keep_browser_open: false,
  viewport_width: 1280,
  viewport_height: 680,
  inter_url_delay_seconds: 0,
  scroll_pause_ms: 2000,
  settle_wait_ms: 1000,
  max_urls: null,
};

function toInt(value, fallback) {
  const numeric = Number.parseInt(value, 10);
  if (Number.isNaN(numeric) || numeric < 0) return fallback;
  return numeric;
}

function toNullableInt(value, fallback = null) {
  const normalized = (value || "").trim();
  if (!normalized) return fallback;
  const numeric = Number.parseInt(normalized, 10);
  return Number.isNaN(numeric) ? fallback : Math.max(1, numeric);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function renderTerminal(lines) {
  const terminal = document.querySelector("#weekly-auto-terminal");
  if (!terminal) return;
  terminal.textContent = lines.join("\n");
  terminal.scrollTop = terminal.scrollHeight;
}

function appendTerminal(lines) {
  const terminal = document.querySelector("#weekly-auto-terminal");
  if (!terminal) return;
  const current = terminal.textContent ? terminal.textContent.split("\n") : [];
  terminal.textContent = current.concat(lines).join("\n");
  terminal.scrollTop = terminal.scrollHeight;
}

function renderStatus(job, showToast) {
  const status = document.querySelector("#weekly-auto-run-status");
  const message = document.querySelector("#weekly-auto-message");
  const stats = document.querySelector("#weekly-auto-stats");
  if (!status || !message || !stats) return;

  if (!job) {
    status.className = "bot-run-status";
    status.innerHTML = "<strong>Sin ejecución</strong><span>Inicia una corrida para ver el estado aquí.</span>";
    return;
  }

  const running = job.status === "RUNNING";
  status.className = `bot-run-status ${running ? "running" : job.status === "PASS" ? "success" : job.status === "FAIL" ? "error" : ""}`;
  status.innerHTML = `<strong>${job.status} · ${job.name}</strong><span>${escapeHtml(job.summary || "Sin resumen disponible.")}</span>`;

  const details = [
    ["Progreso", `${job.completed ?? 0}/${job.total_urls ?? "?"}`],
    ["Éxitos", job.successful ?? 0],
    ["Errores", job.failed ?? 0],
    ["Omitidos", job.skipped ?? 0],
    ["URL actual", job.current_url || "—"],
  ];
  stats.innerHTML = details.map(([label, value]) => `<div class="bot-summary-card"><strong>${escapeHtml(value)}</strong><span>${label}</span></div>`).join("");

  if (running) {
    const started = new Date(job.started_at).toLocaleTimeString("es-CO", { hour: "2-digit", minute: "2-digit" });
    message.textContent = `En progreso (${started}) · índice ${job.current_index || 0} ${job.total_urls ? `/ ${job.total_urls}` : ""}`;
    return;
  }

  if (job.status === "PASS") {
    message.textContent = "Corrida completada correctamente.";
    showToast(`Weekly Auto finalizó correctamente: ${job.summary}`, "info");
  } else if (job.status === "FAIL") {
    message.textContent = `Corrida con errores: ${job.summary}`;
    showToast(`Weekly Auto finalizó con errores: ${job.summary}`, "error");
  } else if (job.status === "CANCELLED") {
    message.textContent = "Corrida detenida por el usuario.";
  }
}

function renderResults(job) {
  const container = document.querySelector("#weekly-auto-results");
  if (!container) return;
  const results = job?.result?.results || [];
  if (!results.length) {
    container.innerHTML = '<div class="bot-empty"><div class="empty-icon">◌</div><strong>Sin resultados todavía</strong><span>Aquí aparecerán las URLs procesadas.</span></div>';
    return;
  }

  container.innerHTML = results
    .map(
      (item) => `<div class="bot-stage">
        <div class="bot-step-content"><strong>${escapeHtml(item.url)}</strong><span>${escapeHtml(item.message)} · ${escapeHtml(String(item.elapsed_seconds))} s · ${escapeHtml(item.status)}</span></div>
        ${item.screenshot ? `<a href="${escapeHtml(item.screenshot)}" target="_blank" rel="noreferrer">Ver captura</a>` : ""}
      </div>`,
    )
    .join("");
}

function readConfig() {
  const name = document.querySelector("#weekly-auto-name").value.trim() || DEFAULT_CONFIG.name;
  const useDefault = document.querySelector("#weekly-auto-use-default").checked;
  const rawUrls = document.querySelector("#weekly-auto-urls").value.trim();
  const browser = document.querySelector("#weekly-auto-browser").value;
  const headless = document.querySelector("#weekly-auto-headless").checked;
  const keepOpen = document.querySelector("#weekly-auto-keep-open").checked;
  const viewportWidth = toInt(document.querySelector("#weekly-auto-viewport-width").value, DEFAULT_CONFIG.viewport_width);
  const viewportHeight = toInt(document.querySelector("#weekly-auto-viewport-height").value, DEFAULT_CONFIG.viewport_height);
  const delaySeconds = toInt(document.querySelector("#weekly-auto-delay").value, DEFAULT_CONFIG.inter_url_delay_seconds);
  const scrollPause = toInt(document.querySelector("#weekly-auto-scroll-pause").value, DEFAULT_CONFIG.scroll_pause_ms);
  const settleWait = toInt(document.querySelector("#weekly-auto-settle-wait").value, DEFAULT_CONFIG.settle_wait_ms);
  const maxUrls = toNullableInt(document.querySelector("#weekly-auto-max-urls").value, DEFAULT_CONFIG.max_urls);

  const urls = rawUrls
    ? rawUrls
        .split("\n")
        .map((line) => line.trim())
        .filter(Boolean)
    : [];

  return {
    name,
    urls,
    use_default_urls: useDefault,
    browser,
    headless,
    keep_browser_open: keepOpen,
    viewport_width: viewportWidth,
    viewport_height: viewportHeight,
    inter_url_delay_seconds: delaySeconds,
    scroll_pause_ms: scrollPause,
    settle_wait_ms: settleWait,
    max_urls: maxUrls,
  };
}

function writeConfig(config) {
  document.querySelector("#weekly-auto-name").value = config.name || DEFAULT_CONFIG.name;
  document.querySelector("#weekly-auto-use-default").checked = config.use_default_urls ?? DEFAULT_CONFIG.use_default_urls;
  document.querySelector("#weekly-auto-urls").value = (config.urls || []).join("\n");
  document.querySelector("#weekly-auto-browser").value = config.browser || DEFAULT_CONFIG.browser;
  document.querySelector("#weekly-auto-headless").checked = config.headless ?? DEFAULT_CONFIG.headless;
  document.querySelector("#weekly-auto-keep-open").checked = config.keep_browser_open ?? DEFAULT_CONFIG.keep_browser_open;
  document.querySelector("#weekly-auto-viewport-width").value = config.viewport_width ?? DEFAULT_CONFIG.viewport_width;
  document.querySelector("#weekly-auto-viewport-height").value = config.viewport_height ?? DEFAULT_CONFIG.viewport_height;
  document.querySelector("#weekly-auto-delay").value = config.inter_url_delay_seconds ?? DEFAULT_CONFIG.inter_url_delay_seconds;
  document.querySelector("#weekly-auto-scroll-pause").value = config.scroll_pause_ms ?? DEFAULT_CONFIG.scroll_pause_ms;
  document.querySelector("#weekly-auto-settle-wait").value = config.settle_wait_ms ?? DEFAULT_CONFIG.settle_wait_ms;
  document.querySelector("#weekly-auto-max-urls").value = config.max_urls ?? "";
}

function saveConfig(config) {
  localStorage.setItem(CONFIG_KEY, JSON.stringify(config));
}

function clearState() {
  state.jobId = null;
  if (state.pollTimer) window.clearInterval(state.pollTimer);
  state.pollTimer = null;
  renderStatus(null);
  renderResults({});
  document.querySelector("#weekly-auto-stop").hidden = true;
  document.querySelector("#weekly-auto-run").disabled = false;
}

async function watchJob(jobId, { showToast, weeklyAutoStatus, cancelWeeklyAuto }) {
  const stopButton = document.querySelector("#weekly-auto-stop");
  const runButton = document.querySelector("#weekly-auto-run");
  const poll = async () => {
    try {
      const job = await weeklyAutoStatus(jobId);
      renderStatus(job, showToast);
      renderResults(job);
      appendTerminal([`[${new Date().toLocaleTimeString("es-CO", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}] [${job.status}] ${job.current_index ?? "-"} / ${job.total_urls ?? "?"} ${job.current_url ?? ""}`.trim()]);
      if (!["RUNNING"].includes(job.status)) {
        stopButton.hidden = true;
        runButton.disabled = false;
        clearInterval(state.pollTimer);
        state.pollTimer = null;
        state.jobId = null;
        localStorage.removeItem(JOB_KEY);
      }
      localStorage.setItem(LAST_JOB_KEY, JSON.stringify(job));
    } catch (error) {
      if (state.pollTimer) window.clearInterval(state.pollTimer);
      stopButton.hidden = true;
      runButton.disabled = false;
      state.jobId = null;
      localStorage.removeItem(JOB_KEY);
      showToast(`No se pudo consultar el estado de Weekly Auto: ${error.message}`, "error");
    }
  };
  await poll();
  // La primera consulta puede encontrar un trabajo que ya terminó.
  if (state.jobId === jobId) {
    state.pollTimer = window.setInterval(poll, 1800);
  }
}

function setupEvents({ showToast, runWeeklyAuto, weeklyAutoStatus, cancelWeeklyAuto }) {
  const runButton = document.querySelector("#weekly-auto-run");
  const stopButton = document.querySelector("#weekly-auto-stop");
  const clearButton = document.querySelector("#weekly-auto-clear");
  const useDefaultInput = document.querySelector("#weekly-auto-use-default");
  const urlsArea = document.querySelector("#weekly-auto-urls");
  const saveButton = document.querySelector("#weekly-auto-save");
  const validateButton = document.querySelector("#weekly-auto-run-preview");

  const toggleUrlMode = () => {
    urlsArea.disabled = useDefaultInput.checked;
    urlsArea.closest(".field").classList.toggle("bot-internal-field", useDefaultInput.checked);
  };
  useDefaultInput.addEventListener("change", toggleUrlMode);

  runButton.addEventListener("click", async () => {
    const config = readConfig();
    if (!config.use_default_urls && !config.urls.length) {
      showToast("Agrega URLs manuales o activa 'Usar lista por defecto'.", "error");
      return;
    }
    if (config.viewport_width < 200 || config.viewport_height < 200) {
      showToast("El viewport debe ser al menos 200x200.", "error");
      return;
    }
    saveConfig(config);
    localStorage.setItem(JOB_KEY, "running");
    runButton.disabled = true;
    stopButton.hidden = false;
    renderTerminal(["[SISTEMA] Iniciando corrida Weekly Auto..."]);
    try {
      const job = await runWeeklyAuto(config);
      state.jobId = job.job_id;
      document.querySelector("#weekly-auto-stop").disabled = false;
      await watchJob(job.job_id, { showToast, weeklyAutoStatus, cancelWeeklyAuto });
      showToast("Corrida Weekly Auto en marcha.", "info");
    } catch (error) {
      runButton.disabled = false;
      stopButton.hidden = true;
      renderTerminal([`[ERROR] ${error.message}`]);
      showToast(error.message, "error");
    }
  });

  stopButton.addEventListener("click", async () => {
    if (!state.jobId) return;
    stopButton.disabled = true;
    try {
      await cancelWeeklyAuto(state.jobId);
      if (state.pollTimer) window.clearInterval(state.pollTimer);
      state.pollTimer = null;
      stopButton.hidden = true;
      runButton.disabled = false;
      renderTerminal(["[CANCELADO] Corrida detenida por el usuario."]);
      showToast("Corrida detenida.", "info");
    } catch (error) {
      showToast(`No se pudo detener: ${error.message}`, "error");
    } finally {
      stopButton.disabled = false;
    }
  });

  saveButton.addEventListener("click", () => {
    const config = readConfig();
    saveConfig(config);
    showToast("Configuración Weekly Auto guardada localmente.", "info");
  });

  validateButton.addEventListener("click", () => {
    const config = readConfig();
    if (!config.use_default_urls && !config.urls.length) {
      showToast("Faltan URLs para validar.", "error");
      return;
    }
    renderTerminal([
      `[SISTEMA] Configuración lista para ${config.use_default_urls ? "usar URLs por defecto" : `${config.urls.length} URLs manuales`}.`,
    ]);
    showToast("Configuración validada.", "info");
  });

  clearButton.addEventListener("click", () => {
    localStorage.removeItem(CONFIG_KEY);
    writeConfig(DEFAULT_CONFIG);
    renderStatus(null);
    renderResults({});
    renderTerminal(["[SISTEMA] Configuración restaurada."]);
    showToast("Configuración reiniciada.", "info");
  });

  // Carga inicial de configuración guardada
  try {
    const stored = JSON.parse(localStorage.getItem(CONFIG_KEY) || "{}");
    writeConfig({ ...DEFAULT_CONFIG, ...stored });
  } catch {
    writeConfig(DEFAULT_CONFIG);
  }
  toggleUrlMode();
}

export function initializeWeeklyAutoModule({ showToast, runWeeklyAuto, weeklyAutoStatus, cancelWeeklyAuto }) {
  setupEvents({ showToast, runWeeklyAuto, weeklyAutoStatus, cancelWeeklyAuto });
}
