"use strict";

// Controlador compartido de los módulos que cargan una matriz, envían formularios
// y verifican los leads. Cada wrapper aporta su identidad y sus funciones API.
export function initializeLeadSubmissionModule(dependencies, options) {
  const config = {
    key: "weekly-forms",
    title: "Weekly Forms",
    fileLabel: "Excel de Weekly Forms (.xlsx)",
    description: "Lee Country/pais, Nivel, URL, formulario y Lead desde QA.xlsx o reportes de landings.",
    readyMessage: "Selecciona la matriz QA.",
    runLabel: "Ejecutar Weekly Forms",
    automationModule: "weekly_forms",
    preview: dependencies.previewWeeklyFormsSpreadsheet,
    runBatch: dependencies.runWeeklyFormsBatch,
    status: dependencies.weeklyFormsStatus,
    cancel: dependencies.cancelWeeklyForms,
    downloadUrl: dependencies.weeklyFormsDownloadUrl,
    viewId: "view-weekly-forms",
    allowManualUrls: false,
    previewManualUrls: null,
    runManualUrls: null,
    ...(options || {}),
  };
  const state = { file: null, manualUrls: [], mapping: null, jobId: null, pollTimer: null };
  const selector = (suffix) => `#${config.key}-${suffix}`;
  const element = (suffix) => document.querySelector(selector(suffix));

  function escapeHtml(value) {
    return String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
  }

  // Inserta un panel independiente para que varios flujos puedan convivir.
  function mount() {
    const view = document.querySelector(`#${config.viewId}`);
    if (!view || document.querySelector(selector("panel"))) return;
    const manualInput = config.allowManualUrls ? `
          <label class="pdp-file-field full"><span>URLs de landings QA (una por línea)</span>
            <textarea id="${config.key}-urls" rows="4" placeholder="https://utel.edu.mx/colombia/...\nhttps://utlenlinea.com/..." aria-label="URLs de landings QA"></textarea>
            <small>El país se infiere desde la URL cuando el Excel no lo incluye.</small>
          </label>` : "";
    const timeoutInput = config.allowManualUrls ? `
          <label class="field"><span>Tiempo máximo de búsqueda (segundos)</span>
            <input id="${config.key}-timeout" type="number" min="15" max="600" step="5" value="90" />
          </label>` : "";
    const fillOnlyInput = config.allowManualUrls ? `
          <label class="toggle-field full-toggle"><input id="${config.key}-fill-only" type="checkbox" />
            <span><strong>Solo llenar, no enviar</strong><small>Prepara y valida los campos sin crear leads ni consultar los CRMs.</small></span>
          </label>` : "";
    view.insertAdjacentHTML("beforeend", `
      <article class="panel" id="${config.key}-panel" style="margin-top:18px;">
        <div class="panel-header">
          <div><p class="eyebrow accent">${config.title}</p><h3>Envío y verificación de leads</h3>
          <p class="panel-subtitle">${config.description} Procesa 5 filas y descansa 60 segundos.</p></div>
          <span class="status-badge success">5 + PAUSA 60 S</span>
        </div>
        <div class="bot-fields">
          ${manualInput}
          <label class="pdp-file-field full"><span>${config.fileLabel}</span>
            <input id="${config.key}-file" type="file" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" />
            <small id="${config.key}-file-name">${config.readyMessage}</small>
          </label>
          <label class="field"><span>Buscar el Lead en</span><select id="${config.key}-destination">
            <option value="both">InConcert y Balanceador</option><option value="inconcert">Solo InConcert</option><option value="balanceador">Solo Balanceador</option>
          </select></label>
          <label class="field"><span>Navegador</span><select id="${config.key}-browser">
            <option value="chrome">Google Chrome - Perfil QA</option><option value="chromium">Chromium aislado</option><option value="firefox">Firefox</option>
          </select></label>
          ${timeoutInput}
          ${fillOnlyInput}
          <label class="toggle-field full-toggle"><input id="${config.key}-visible" type="checkbox" checked />
            <span><strong>Mostrar el navegador</strong><small>Permite observar cómo identifica, llena y envía cada formulario.</small></span>
          </label>
        </div>
        <div class="bot-flow-actions" style="margin-top:12px;">
          <div><button class="secondary-button" id="${config.key}-analyze" type="button">Analizar Excel</button>
            <button class="secondary-button" id="${config.key}-download" type="button" hidden>Descargar Excel actualizado</button></div>
          <div><button class="danger-button" id="${config.key}-stop" type="button" hidden>Detener</button>
            <button class="primary-button" id="${config.key}-run" type="button" disabled>${config.runLabel} <span>→</span></button></div>
        </div>
        <div class="bot-run-status" id="${config.key}-status">Carga y analiza el Excel para comenzar.</div>
        <pre class="bot-terminal" id="${config.key}-terminal" aria-live="polite">[SISTEMA] Esperando Excel.</pre>
        <div id="${config.key}-summary" class="pdp-summary" style="margin-top:12px;display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px;"></div>
      </article>`);
  }

  function setTerminal(message) {
    const terminal = element("terminal");
    if (!terminal) return;
    terminal.textContent = message;
    terminal.scrollTop = terminal.scrollHeight;
  }

  function renderJob(job) {
    const status = element("status");
    const summary = element("summary");
    const download = element("download");
    if (!status || !summary) return;
    const running = ["QUEUED", "RUNNING"].includes(job.status);
    const successful = job.status === "PASS";
    const completed = job.completed || 0;
    const success = job.success ?? job.successful ?? 0;
    status.className = `bot-run-status ${running ? "running" : successful ? "success" : job.status === "FAIL" ? "error" : ""}`;
    status.innerHTML = `<strong>${escapeHtml(job.status)}</strong><span>${escapeHtml(job.phase || job.summary || "")}</span>`;
    summary.innerHTML = [
      ["Procesadas", `${completed}/${job.total || 0}`], [job.fill_only ? "Formularios OK" : "Con Lead", success],
      ["Sin completar", job.failed || 0], ["Fila actual", job.current_row || "—"],
      ["Tandas", job.completed_batches || 0], ["Tamaño", job.batch_size || 5],
    ].map(([label, value]) => `<div class="bot-summary-card"><strong>${escapeHtml(value)}</strong><span>${label}</span></div>`).join("");
    setTerminal([
      `[${job.status}] ${completed}/${job.total || 0} filas`,
      `[FASE] ${job.phase || "Preparando"}`,
      job.fill_only ? "[MODO] Solo llenar: no se enviarán formularios ni se consultarán CRMs." : "",
      job.current_program ? `[CASO] ${job.current_program}` : "",
      job.last_error ? `[DETALLE] ${job.last_error}` : "",
    ].filter(Boolean).join("\n"));
    if (download) download.hidden = !job.download_url;
  }

  // Consulta el trabajo hasta que el backend informa un estado terminal.
  async function watch() {
    let stillRunning = true;
    const poll = async () => {
      try {
        const job = await config.status(state.jobId);
        renderJob(job);
        if (!["QUEUED", "RUNNING"].includes(job.status)) {
          stillRunning = false;
          window.clearInterval(state.pollTimer);
          state.pollTimer = null;
          element("stop").hidden = true;
          element("run").disabled = false;
          dependencies.showToast(
            job.status === "PASS" ? `${config.title} finalizó.` : `${config.title} terminó: ${job.summary || job.status}`,
            job.status === "PASS" ? "info" : "error",
          );
        }
      } catch (error) {
        window.clearInterval(state.pollTimer);
        state.pollTimer = null;
        dependencies.showToast(`No se pudo consultar ${config.title}: ${error.message}`, "error");
      }
    };
    await poll();
    if (stillRunning && state.jobId && !state.pollTimer) state.pollTimer = window.setInterval(poll, 1800);
  }

  // Enlaza los controles de carga, análisis, ejecución, cancelación y descarga.
  function setup() {
    const fileInput = element("file");
    const analyze = element("analyze");
    const run = element("run");
    const stop = element("stop");
    const download = element("download");
    const urlsInput = config.allowManualUrls ? element("urls") : null;

    const hasInput = () => Boolean(state.file || state.manualUrls.length);

    fileInput.addEventListener("change", () => {
      state.file = fileInput.files?.[0] || null;
      state.mapping = null;
      run.disabled = !hasInput();
      download.hidden = true;
      element("file-name").textContent = state.file?.name || config.readyMessage;
    });

    urlsInput?.addEventListener("input", () => {
      state.manualUrls = urlsInput.value.split(/\r?\n/).map((value) => value.trim()).filter(Boolean);
      state.mapping = null;
      run.disabled = !hasInput();
      if (state.manualUrls.length) {
        state.file = null;
        fileInput.value = "";
        element("file-name").textContent = "Se usarán las URLs pegadas manualmente.";
      }
    });

    analyze.addEventListener("click", async () => {
      if (!hasInput()) return dependencies.showToast(`Selecciona un Excel o pega URLs para ${config.title}.`, "error");
      analyze.disabled = true;
      try {
        const preview = state.file
          ? await config.preview(state.file)
          : await config.previewManualUrls(state.manualUrls);
        const sheet = preview.sheets?.[0];
        if (!sheet) throw new Error("No se encontraron URLs UTEL permitidas para procesar.");
        state.mapping = sheet.mapping;
        run.disabled = false;
        // El backend agrega hojas espejo y descarta Leads ya existentes antes
        // de calcular el total real que se ejecutará.
        const total = preview.total_rows ?? sheet.total_rows ?? sheet.rows?.length ?? 0;
        const invalid = sheet.invalid_rows?.length || 0;
        setTerminal(`[ANÁLISIS] ${total} filas pendientes detectadas en ${sheet.name}.\n[REGLA] 5 procesos + pausa de 60 segundos.${invalid ? `\n[AVISO] ${invalid} URLs omitidas por dominio o formato.` : ""}`);
        dependencies.showToast(`${total} filas de ${config.title} listas.`, "info");
      } catch (error) {
        dependencies.showToast(error.message, "error");
      } finally {
        analyze.disabled = false;
      }
    });

    run.addEventListener("click", async () => {
      if ((!state.file && !state.manualUrls.length) || !state.mapping) return;
      run.disabled = true;
      stop.hidden = false;
      download.hidden = true;
      try {
        const visible = element("visible").checked;
        const batchConfig = {
          name: config.title, automation_module: config.automationModule, environment: "production",
          dry_run: false, workflow_mode: "form_validation",
          lead_search_destination: element("destination").value,
          parallel_crm_search: true, randomize_academic_selections: true,
          crm_search_timeout_seconds: Math.min(600, Math.max(15, Number(element("timeout")?.value || 90))),
          fill_only: Boolean(element("fill-only")?.checked),
          browser: element("browser").value, headless: !visible, keep_browser_open: false,
        };
        const job = state.file
          ? await config.runBatch(state.file, batchConfig, state.mapping)
          : await config.runManualUrls(state.manualUrls, batchConfig);
        state.jobId = job.job_id;
        renderJob(job);
        await watch();
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
        await config.cancel(state.jobId);
        dependencies.showToast("Detención solicitada.", "info");
      } catch (error) {
        dependencies.showToast(error.message, "error");
      } finally {
        stop.disabled = false;
      }
    });

    download.addEventListener("click", () => {
      if (!state.jobId) return;
      const anchor = document.createElement("a");
      anchor.href = config.downloadUrl(state.jobId);
      anchor.download = `${config.key}-resultado.xlsx`;
      anchor.click();
    });
  }

  mount();
  setup();
}
