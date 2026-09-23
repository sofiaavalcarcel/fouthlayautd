"use strict";

// Controlador visual del Bot: formulario, pasos, validación y ejecución.
const STORAGE_KEY = "qa-automation.leads-deploy-config";
const ACTIVE_SINGLE_JOB_KEY = "qa-automation.leads-deploy-active-job";
const LAST_SINGLE_JOB_KEY = "qa-automation.leads-deploy-last-job";
const ACTIVE_BATCH_JOB_KEY = "qa-automation.leads-deploy-active-batch";
const LAST_BATCH_JOB_KEY = "qa-automation.leads-deploy-last-batch";
const AUTO_DOWNLOADED_BATCH_KEY = "qa-automation.leads-deploy-auto-downloaded-batch";

const state = {
  config: {
    name: "Bot Leads Deploy",
    environment: "sandbox",
    dry_run: true,
    country: "ecuador",
    utel_url: "",
    inconcert_url: "",
    modality: "En linea",
    level: "Licenciatura",
    form_type: "lateral",
    program_selection_strategy: "first",
    program_name: "",
    submit_success_pattern: "Env\u00edo correcto|Pronto recibir\u00e1s informaci\u00f3n",
    submit_error_pattern: "Error al enviar|Contacta a soporte|error|invalido|inválido|obligatorio|requerido|fall",
    browser: "chromium",
    headless: true,
    keep_browser_open: false,
    lead: { name: "pending", email: "pending@testingUtel.com", phone: "900000000" },
  },
  activeJobId: null,
  pollTimer: null,
  workflowMode: "product_release",
};

export function isSafeUtelRetry(item) {
  // Solo se reintenta cuando el backend confirma que no observó el
  // POST /api/forms. Los resultados inciertos quedan protegidos para evitar duplicados.
  return item?.result?.status === "FAIL" && item.result.utel_submission_attempted === false;
}

const stageLabels = {
  utel_open: "Abrir UTEL",
  utel_navigation: "Navegar modalidad/nivel",
  utel_form: "Identificar formulario",
  utel_fill: "Rellenar formulario",
  utel_submit: "Enviar formulario",
  dry_run_stop: "Detener antes del envio",
  inconcert_open: "Abrir InConcert",
  inconcert_login: "Login InConcert",
  inconcert_contacts: "Abrir contactos",
  inconcert_search: "Buscar lead",
  lead_balancer_search: "Buscar lead en Balanceador",
  inconcert_manage: "Abrir Gestionar",
  inconcert_conversion: "Confirmar conversion",
  config: "Validar configuracion",
  startup: "Iniciar automatizacion",
};

function renderModuleShell() {
  const view = document.querySelector("#view-leads-deploy");
  view.innerHTML = `
    <div class="bot-breadcrumb"><span>Espacio de trabajo</span><b>/</b><strong>Bot Leads Deploy</strong></div>
    <div class="section-intro bot-page-intro"><p class="eyebrow accent">Automatizacion Leads Deploy</p><p class="muted">Automatiza y valida los envios de leads en UTEL + InConcert de forma rapida y confiable.</p></div>
    <article class="bot-hero"><div class="bot-hero-icon">◇</div><div><div class="bot-hero-title"><h3>Bot Leads Deploy</h3><span class="status-badge success">ACTIVO</span></div><p>Ejecuta el flujo de Leads Deploy, valida cada caso y descarga automaticamente el Excel actualizado.</p></div><button class="secondary-button" id="leads-deploy-guide" type="button">Ver guia rapida</button></article>
    <div class="bot-layout">
      <article class="panel bot-config-panel">
        <div class="panel-header"><div><p class="eyebrow">Configuracion</p><h3>Define la verificacion</h3><p class="panel-subtitle">Configura los datos necesarios para ejecutar el caso.</p></div><span class="status-badge success">● PLAYWRIGHT</span></div>
        <div class="bot-fields">
          <label class="field full"><span>Nombre de la ejecucion</span><input id="leads-deploy-name" type="text" placeholder="Bot Leads Deploy" /></label>
          <label class="field"><span>Pais</span><select id="leads-deploy-country">
            <option value="">Selecciona un pais</option>
            <option value="mexico">Mexico</option>
            <option value="ecuador">Ecuador</option>
            <option value="colombia">Colombia</option>
            <option value="peru">Peru</option>
            <option value="chile">Chile</option>
            <option value="argentina">Argentina</option>
            <option value="united states">Estados Unidos</option>
            <option value="bolivia">Bolivia</option>
            <option value="paraguay">Paraguay</option>
            <option value="republica dominicana">Republica Dominicana</option>
            <option value="guatemala">Guatemala</option>
            <option value="panama">Panama</option>
            <option value="el salvador">El Salvador</option>
            <option value="global">Global</option>
            <option value="filipinas">Filipinas</option>
            <option value="india">India</option>
          </select></label>
          <label class="field"><span>Formulario</span><select id="leads-deploy-form-type"><option value="lateral">LateralBLC</option><option value="tarjeta">TarjetaBLC</option><option value="footer">FooterBLC</option></select></label>
          <label class="field full bot-internal-field"><span>URL UTEL</span><input id="leads-deploy-utel-url" type="url" placeholder="Se carga desde el Excel segun el pais" /><small id="leads-deploy-utel-url-status">Selecciona una fila del Excel; tambien puedes escribirla manualmente.</small></label>
          <div class="field full"><span>Importar Excel</span><div class="file-action-row"><input id="leads-deploy-spreadsheet" type="file" accept=".xlsx" /><button class="secondary-button" id="leads-deploy-analyze-spreadsheet" type="button">Analizar Excel</button></div><small id="leads-deploy-spreadsheet-status">Adjunta el archivo y pulsa Analizar Excel para revisar sus columnas.</small><div id="leads-deploy-column-mapping"></div></div>
          <label class="field full"><span>Fila importada</span><select id="leads-deploy-spreadsheet-row"><option value="">Selecciona una fila después de analizar</option></select></label>
          <label class="field full"><span>URL InConcert</span><input id="leads-deploy-inconcert-url" type="url" placeholder="https://..." /></label>
          <label class="field"><span>Modalidad</span><input id="leads-deploy-modality" type="text" placeholder="En linea" /></label>
          <label class="field bot-internal-field" hidden aria-hidden="true"><span>Nivel</span><input id="leads-deploy-level" type="hidden" value="Licenciatura" /></label>
          <label class="field"><span>Entorno</span><select id="leads-deploy-environment"><option value="sandbox">Sandbox</option><option value="production">Producción</option></select></label>
          <label class="toggle-field"><input id="leads-deploy-dry-run" type="checkbox" checked /><span><strong>Dry run seguro</strong><small>Rellena el formulario sin enviar leads reales</small></span></label>
          <label class="field"><span>Estrategia de programa</span><select id="leads-deploy-program-strategy"><option value="exact_match">Coincidencia exacta</option><option value="first">Primer programa visible</option></select></label>
          <label class="field full"><span>Nombre exacto del programa</span><input id="leads-deploy-program-name" type="text" placeholder="Obligatorio con coincidencia exacta" /></label>
          <label class="field full"><span>Patron de confirmacion (opcional)</span><input id="leads-deploy-success-pattern" type="text" placeholder="Ej. gracias|exito" /></label>
          <label class="field full"><span>Patron de error</span><input id="leads-deploy-error-pattern" type="text" /></label>
          <label class="field"><span>Navegador</span><select id="leads-deploy-browser"><option value="chromium">Chromium aislado</option><option value="chrome">Google Chrome - Perfil QA</option><option value="firefox">Firefox</option><option value="webkit">WebKit</option></select></label>
          <label class="toggle-field"><input id="leads-deploy-headless" type="checkbox" checked /><span><strong>Ejecutar en segundo plano</strong><small>Sin controlar tu navegador de trabajo</small></span></label>
          <label class="toggle-field full-toggle"><input id="leads-deploy-keep-browser-open" type="checkbox" /><span><strong>Modo debug visible</strong><small>Muestra el navegador durante la ejecucion y lo deja abierto al final</small></span></label>
        </div>
        <div class="security-note"><span>i</span><p>Las credenciales de InConcert se leen desde .env como INCONCERT_USERNAME/INCONCERT_PASSWORD o CRM_USERNAME/CRM_PASSWORD. No se guardan en la interfaz.</p></div>
        <div class="bot-step-builder bot-generated-lead-hidden" aria-hidden="true">
          <div class="builder-heading"><div><p class="eyebrow">Lead de prueba</p><h3>Datos generados automaticamente</h3><p class="panel-subtitle">Se crean al ejecutar cada caso.</p></div><span class="step-hint">Sin contrasenas</span></div>
          <div class="bot-fields step-fields">
            <label class="field full"><span>Nombre de prueba</span><input id="leads-deploy-lead-name" type="text" readonly /></label>
            <label class="field"><span>Email de prueba</span><input id="leads-deploy-lead-email" type="email" readonly /></label>
            <label class="field"><span>Telefono de prueba</span><input id="leads-deploy-lead-phone" type="tel" readonly /></label>
          </div>
          <p class="muted">El nombre y email se generan automáticamente. En dry run el teléfono es sintético; los envíos reales usan el banco autorizado por país, salvo que QA active explícitamente el modo de teléfonos sintéticos válidos.</p>
        </div>
      </article>
      <section class="bot-error-log-panel bot-error-log-panel--standalone">
        <div class="bot-error-log-heading"><div><p class="eyebrow">Diagnóstico</p><h4>Log exclusivo de errores</h4><small>Incluye fila, etapa, URL, selector, captura y mensaje técnico completo.</small></div><div><button class="secondary-button" id="leads-deploy-copy-errors" type="button" disabled>Copiar errores</button><button class="secondary-button" id="leads-deploy-download-errors" type="button" disabled>Descargar .txt</button></div></div>
        <pre class="bot-error-terminal" id="leads-deploy-error-terminal" aria-live="polite">Sin errores registrados en esta ejecución.</pre>
      </section>
      <article class="panel bot-flow-panel">
        <div class="panel-header"><div><p class="eyebrow">Resultado</p><h3>Seguimiento de ejecucion</h3><p class="panel-subtitle">Sigue en tiempo real el progreso del flujo.</p></div><span class="step-count">UTEL → InConcert</span></div>
        <div class="bot-validation" id="leads-deploy-validation">Completa los campos con * y pulsa <strong>Ejecutar prueba</strong>. En Dry run no necesitas URL ni credenciales de InConcert.</div>
        <div class="bot-run-status" id="leads-deploy-run-status">El flujo todavia no se ha ejecutado.</div>
        <div class="bot-flow-actions"><div><button class="secondary-button" id="leads-deploy-clear" type="button">Limpiar</button></div><div><button class="secondary-button" id="leads-deploy-save" type="button">Guardar</button><button class="secondary-button" id="leads-deploy-validate" type="button">Validar</button><button class="secondary-button" id="leads-deploy-batch-run" type="button" hidden>Ejecutar todas las filas</button><button class="secondary-button" id="leads-deploy-retry-errors" type="button" hidden>Reintentar errores</button><button class="danger-button" id="leads-deploy-stop" type="button" hidden>Detener ejecución</button><button class="primary-button" id="leads-deploy-run" type="button">Ejecutar prueba <span>-></span></button></div></div>
        <pre class="bot-terminal" id="leads-deploy-terminal" aria-live="polite">[sistema] Esperando el inicio de la ejecución...</pre>
        <div class="pdp-summary" id="leads-deploy-summary"></div>
        <div class="bot-steps-list" id="leads-deploy-stages-list"></div>
        <details class="bot-preview"><summary>Ver configuracion generada</summary><pre id="leads-deploy-preview">{}</pre></details>
      </article>
    </div>`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function organizeBotForm() {
  const fields = document.querySelector("#view-leads-deploy .bot-config-panel > .bot-fields");
  if (!fields) return;
  // Algunos controles (como el selector de Excel) viven en un div porque
  // contienen un botón adicional; todos deben moverse como un solo campo.
  const field = (id) => document.querySelector(`#${id}`)?.closest("label, .field") || null;
  const sections = document.createElement("div");
  sections.className = "bot-form-sections";
  sections.innerHTML = `
    <section class="bot-form-section"><div class="bot-section-heading"><span class="step-number">1</span><div><strong>Origen del caso</strong><small>Selecciona el país y carga la fila del Excel</small></div></div><div class="bot-fields" data-section="source"></div></section>
    <details class="bot-advanced"><summary>Opciones avanzadas <span>Solo necesarias para casos especiales</span></summary><div class="bot-fields" data-section="advanced"></div></details>`;
  const source = sections.querySelector('[data-section="source"]');
  const advanced = sections.querySelector('[data-section="advanced"]');
  const moveFields = (ids, target) => ids.forEach((id) => {
    const node = field(id);
    if (node) target.append(node);
  });
  moveFields(["leads-deploy-name", "leads-deploy-country", "leads-deploy-spreadsheet"], source);
  moveFields(["leads-deploy-spreadsheet-row", "leads-deploy-utel-url"], advanced);
  moveFields([
  "leads-deploy-modality",
  "leads-deploy-level",
  "leads-deploy-form-type",
  "leads-deploy-program-strategy",
  "leads-deploy-program-name",
  "leads-deploy-success-pattern",
  "leads-deploy-error-pattern",
  "leads-deploy-inconcert-url",
  "leads-deploy-browser",
  "leads-deploy-dry-run",
  "leads-deploy-headless",
  "leads-deploy-keep-browser-open",
  "leads-deploy-environment",
  ], advanced);
  const securityNote = document.querySelector("#view-leads-deploy .security-note");
  if (securityNote) advanced.append(securityNote);
  fields.replaceWith(sections);
  ["leads-deploy-country", "leads-deploy-utel-url", "leads-deploy-modality"].forEach((id) => {
    const title = field(id)?.querySelector("span");
    if (title && !title.textContent.includes("*")) title.textContent += " *";
  });
}

function loadConfig() {
  try {
    const storedConfig = JSON.parse(localStorage.getItem(STORAGE_KEY));
    if (storedConfig?.lead) state.config = { ...state.config, ...storedConfig, lead: { ...state.config.lead, ...storedConfig.lead } };
    if (state.config.program_selection_strategy === "exact_match" && !state.config.program_name) state.config.program_selection_strategy = "first";
    if (!state.config.submit_success_pattern) state.config.submit_success_pattern = "Env\u00edo correcto|Pronto recibir\u00e1s informaci\u00f3n";
    if (!state.config.submit_error_pattern) state.config.submit_error_pattern = "Error al enviar|Contacta a soporte|error|invalido|inválido|obligatorio|requerido|fall";
  } catch {
    localStorage.removeItem(STORAGE_KEY);
  }
}

function getInputValue(selector, { asBoolean = false } = {}) {
  const element = document.querySelector(selector);
  if (!element) return asBoolean ? false : "";
  if (asBoolean) return Boolean(element.checked);
  return element.value;
}

function setInputValue(selector, value, { asBoolean = false } = {}) {
  const element = document.querySelector(selector);
  if (!element) return;
  if (asBoolean) {
    element.checked = Boolean(value);
    return;
  }
  element.value = value ?? "";
}

const COUNTRY_VALUE_ALIASES = {
  "mexico": "mexico",
  "méxico": "mexico",
  "ecuador": "ecuador",
  "colombia": "colombia",
  "peru": "peru",
  "perú": "peru",
  "chile": "chile",
  "argentina": "argentina",
  "usa": "united states",
  "united states": "united states",
  "estados unidos": "united states",
  "bolivia": "bolivia",
  "paraguay": "paraguay",
  "dominicana": "republica dominicana",
  "republica dominicana": "republica dominicana",
  "república dominicana": "republica dominicana",
  "dominican republic": "republica dominicana",
  "guatemala": "guatemala",
  "panama": "panama",
  "panamá": "panama",
  "el salvador": "el salvador",
  "global": "global",
  "filipinas": "filipinas",
  "philippines": "filipinas",
  "india": "india",
};

function canonicalCountryValue(value) {
  const normalized = String(value || "")
    .trim()
    .toLocaleLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "");
  return COUNTRY_VALUE_ALIASES[normalized] || normalized;
}

function setCountryValue(value) {
  const country = document.querySelector("#leads-deploy-country");
  if (!country) return;
  const canonical = canonicalCountryValue(value);
  country.value = [...country.options].some((option) => option.value === canonical)
    ? canonical
    : "";
}

function readForm() {
  state.config.name = (getInputValue("#leads-deploy-name") || "").trim();
  state.config.environment = getInputValue("#leads-deploy-environment") || state.config.environment;
  state.config.dry_run = getInputValue("#leads-deploy-dry-run", { asBoolean: true });
  state.config.country = canonicalCountryValue(getInputValue("#leads-deploy-country"));
  state.config.utel_url = (getInputValue("#leads-deploy-utel-url") || "").trim();
  state.config.inconcert_url = (getInputValue("#leads-deploy-inconcert-url") || "").trim();
  state.config.modality = (
  getInputValue("#leads-deploy-modality") ||
  state.config.modality ||
  "En linea"
  ).trim();

  state.config.level = (
  getInputValue("#leads-deploy-level") ||
  state.config.level ||
  "Licenciatura"
  ).trim();
  state.config.form_type = getInputValue("#leads-deploy-form-type") || state.config.form_type;
  state.config.program_selection_strategy = getInputValue("#leads-deploy-program-strategy") || state.config.program_selection_strategy;
  state.config.program_name = (getInputValue("#leads-deploy-program-name") || "").trim();
  state.config.submit_success_pattern = (getInputValue("#leads-deploy-success-pattern") || state.config.submit_success_pattern);
  state.config.submit_error_pattern = (getInputValue("#leads-deploy-error-pattern") || state.config.submit_error_pattern);
  state.config.browser = getInputValue("#leads-deploy-browser") || state.config.browser;
  state.config.headless = getInputValue("#leads-deploy-headless", { asBoolean: true });
  state.config.keep_browser_open = getInputValue("#leads-deploy-keep-browser-open", { asBoolean: true });
  state.config.lead = {
    name: (getInputValue("#leads-deploy-lead-name") || "pending").trim() || "pending",
    email: (getInputValue("#leads-deploy-lead-email") || "").trim(),
    phone: (getInputValue("#leads-deploy-lead-phone") || "").trim(),
  };
}

function writeForm() {
  setInputValue("#leads-deploy-name", state.config.name);
  setInputValue("#leads-deploy-environment", state.config.environment);
  setInputValue("#leads-deploy-dry-run", state.config.dry_run, { asBoolean: true });
  setCountryValue(state.config.country);
  setInputValue("#leads-deploy-utel-url", state.config.utel_url);
  setInputValue("#leads-deploy-inconcert-url", state.config.inconcert_url);
  setInputValue("#leads-deploy-modality", state.config.modality);
  setInputValue("#leads-deploy-level", state.config.level);
  setInputValue("#leads-deploy-form-type", state.config.form_type);
  setInputValue("#leads-deploy-program-strategy", state.config.program_selection_strategy);
  setInputValue("#leads-deploy-program-name", state.config.program_name);
  setInputValue("#leads-deploy-success-pattern", state.config.submit_success_pattern);
  setInputValue("#leads-deploy-error-pattern", state.config.submit_error_pattern);
  setInputValue("#leads-deploy-browser", state.config.browser);
  setInputValue("#leads-deploy-headless", state.config.headless, { asBoolean: true });
  setInputValue("#leads-deploy-keep-browser-open", state.config.keep_browser_open, { asBoolean: true });
  setInputValue("#leads-deploy-lead-name", state.config.lead.name);
  setInputValue("#leads-deploy-lead-email", state.config.lead.email);
  setInputValue("#leads-deploy-lead-phone", state.config.lead.phone);
}

function saveConfig(showToast) {
  readForm();
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state.config));
  renderPreview();
  showToast("Configuracion UTEL guardada en este equipo.", "info");
}

function renderPreview() {
  const preview = document.querySelector("#leads-deploy-preview");
  const safeConfig = { ...state.config, lead: { ...state.config.lead } };
  preview.textContent = JSON.stringify(safeConfig, null, 2);
}

function setValidation(message, type = "") {
  const validation = document.querySelector("#leads-deploy-validation");
  validation.className = `bot-validation ${type}`;
  validation.textContent = message;
}

function validateConfig(showToast) {
  readForm();
  const workflowMode = state.workflowMode || "product_release";
  const urlFields = [["URL de UTEL", state.config.utel_url]];
  if (!state.config.dry_run && workflowMode !== "form_validation") urlFields.push(["URL de InConcert", state.config.inconcert_url]);
  if (workflowMode !== "form_validation" && state.config.program_selection_strategy === "exact_match" && !state.config.program_name) {
    setValidation("Indica el nombre exacto del programa o selecciona el primer programa visible.", "error");
    return null;
  }
  const missingFields = [
    ["nombre del bot", state.config.name],
    ...(workflowMode === "form_validation" ? [] : [["pais", state.config.country]]),
      ["email del lead", state.config.lead.email],
    ["telefono del lead", state.config.lead.phone],
  ].filter(([, value]) => !value);

  if (missingFields.length) {
    const message = `Falta completar ${missingFields[0][0]}.`;
    setValidation(message, "error");
    showToast(message, "error");
    return null;
  }
  const invalidUrl = urlFields.find(([, value]) => !/^https?:\/\//i.test(value));
  if (invalidUrl) {
    const message = `${invalidUrl[0]} debe comenzar con http:// o https://.`;
    setValidation(message, "error");
    showToast(message, "error");
    return null;
  }
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(state.config.lead.email)) {
    const message = "El email del lead no tiene un formato valido.";
    setValidation(message, "error");
    showToast(message, "error");
    return null;
  }

  setValidation("Configuracion valida. El flujo puede ejecutarse en segundo plano.", "success");
  showToast("Configuracion validada correctamente.", "info");
  renderPreview();
  return JSON.parse(JSON.stringify(state.config));
}

function renderRunResult(result) {
  const status = document.querySelector("#leads-deploy-run-status");
  const passed = result.status === "PASS";
  status.className = `bot-run-status ${passed ? "success" : "error"}`;
  status.innerHTML = `<strong>${passed ? "FLUJO COMPLETADO" : "FLUJO FALLIDO"}</strong><span>${escapeHtml(result.summary)} · ${escapeHtml(String(result.duration_seconds))} s</span>`;
  renderStages(result.stages || []);
  renderSummary(result);
}

function renderSummary(result) {
  const summary = document.querySelector("#leads-deploy-summary");
  const statusLabel = (value) => ({ success: "EXITOSO", failed: "ERROR", pending: "PENDIENTE", skipped: "NO ENVIADO" })[value] || value;
  summary.innerHTML = [
    ["Pais", result.country],
    ["Modalidad", result.modality],
    ["Nivel", result.level],
    ["Envío del formulario", statusLabel(result.utel_submission)],
    ["Login InConcert", statusLabel(result.inconcert_login)],
    ["Lead", statusLabel(result.lead_found)],
    ["Conversion", statusLabel(result.conversion_found)],
  ].map(([label, value]) => `<div class="pdp-summary-card"><strong>${escapeHtml(value)}</strong><span>${escapeHtml(label)}</span>${label === "Envío del formulario" ? `<small>${escapeHtml(result.utel_submission_message || "Sin detalle")}</small>` : ""}</div>`).join("");
}

function renderBatchResults(job) {
  const summary = document.querySelector("#leads-deploy-summary");
  const results = job.results || [];
  if (!results.length) return;
  summary.innerHTML = `<div class="batch-result-list"><strong>Detalle de filas procesadas</strong>${results.map((item) => {
    const result = item.result || {};
    const failedStage = (result.stages || []).find((stage) => stage.status === "FAIL");
    const ok = result.status === "PASS";
    return `<div class="batch-result-item ${ok ? "success" : "error"}"><span>${ok ? "OK" : "ERROR"}</span><strong>Fila ${escapeHtml(item.row?.row_number)} · ${escapeHtml(item.row?.program_name || item.row?.level || "Sin programa")}</strong><small>${escapeHtml(ok ? result.summary : failedStage?.message || result.summary || "Error no especificado")}</small></div>`;
  }).join("")}</div>`;
}

function renderTerminal(lines) {
  const terminal = document.querySelector("#leads-deploy-terminal");
  if (!terminal) return;
  terminal.textContent = lines.join("\n");
  terminal.scrollTop = terminal.scrollHeight;
}

function appendTerminal(lines) {
  const terminal = document.querySelector("#leads-deploy-terminal");
  if (!terminal) return;
  const previous = terminal.textContent.trimEnd();
  terminal.textContent = [previous, ...lines].filter(Boolean).join("\n");
  terminal.scrollTop = terminal.scrollHeight;
}

export function buildErrorLog(job) {
  const failures = [];
  (job.results || []).forEach((item) => {
    const result = item.result || {};
    // Un PASS puede conservar etapas fallidas como evidencia de un bloqueo ya
    // recuperado. El log exclusivo solo debe enumerar resultados definitivos.
    if (result.status !== "FAIL") return;
    // Mientras una fila está activa existe un checkpoint preventivo marcado
    // como FAIL; no es un error hasta que el runner entrega su estado final.
    if (result.utel_submission === "pending" && result.utel_submission_attempted == null) return;
    const failedStages = (result.stages || []).filter((stage) => stage.status === "FAIL");
    if (!failedStages.length) {
      failedStages.push({ stage: "ejecucion", message: result.summary || "La ejecución falló sin detalle de etapa." });
    }
    failedStages.forEach((stage) => failures.push({ item, result, stage }));
  });
  if (job.status === "FAIL" && job.summary) {
    failures.push({
      item: { row: { row_number: job.current_row, level: job.current_program } },
      result: { dry_run: job.dry_run },
      stage: { stage: "lote", message: job.summary },
    });
  }
  if (!failures.length) return "";
  const lines = [
    "LOG EXCLUSIVO DE ERRORES - BOT UTEL",
    `Generado: ${new Date().toLocaleString("es-CO")}`,
    `Trabajo: ${job.job_id || "sin-id"}`,
    `Progreso: ${job.completed ?? failures.length}/${job.total ?? failures.length} · Errores: ${job.failed ?? failures.length}`,
    "=".repeat(80),
  ];
  failures.forEach(({ item, result, stage }, index) => {
    const row = item.row || {};
    lines.push(
      "",
      `ERROR ${index + 1}`,
      `Fila: ${row.row_number || "?"}`,
      `Hoja: ${row.sheet || "No disponible"}`,
      `Caso/Nivel: ${row.program_name || row.level || "Sin programa"}`,
      `País: ${row.country || result.country || "No disponible"}`,
      `Formulario: ${row.form_type || result.form_type || "No disponible"}`,
      `Modalidad: ${result.modality || "No disponible"}`,
      `Programa seleccionado: ${result.selected_program_name || "No seleccionado"}`,
      `Modo: ${result.dry_run ? "DRY RUN - SIN ENVÍO" : "ENVÍO REAL"}`,
      `URL de entrada: ${row.utel_url || "No disponible"}`,
      `Datos de prueba: ${result.lead_name || "-"} · ${result.lead_email || "-"} · ${result.lead_phone || "-"}`,
      `Etapa: ${stageLabels[stage.stage] || stage.stage}`,
      `URL al fallar: ${stage.url || "No disponible"}`,
      `Selector: ${stage.selector || "No disponible"}`,
      `Captura: ${stage.screenshot || "No disponible"}`,
      "Mensaje completo:",
      stage.message || result.summary || "Error no especificado",
      "-".repeat(80),
    );
  });
  return lines.join("\n");
}

function renderErrorLog(job) {
  const terminal = document.querySelector("#leads-deploy-error-terminal");
  if (!terminal) return;
  const content = buildErrorLog(job);
  terminal.textContent = content || "Sin errores registrados en esta ejecución.";
  terminal.dataset.log = content;
  terminal.scrollTop = terminal.scrollHeight;
  document.querySelector("#leads-deploy-copy-errors").disabled = !content;
  document.querySelector("#leads-deploy-download-errors").disabled = !content;
}

function renderBatchTerminal(job, running = false) {
  const now = new Date().toLocaleTimeString("es-CO", { hour12: false });
  const lines = [`[${now}] [LOTE] ${job.completed || 0}/${job.total || 0} filas procesadas · OK: ${job.success || 0} · ERROR: ${job.failed || 0} · PENDIENTE CRM: ${job.pending || 0}`];
  (job.results || []).forEach((item) => {
    const label = `Fila ${item.row?.row_number || "?"} · ${item.row?.program_name || item.row?.level || "Sin programa"}`;
    const result = item.result || {};
    if (result.lead_name || result.lead_email || result.lead_phone) {
      lines.push(`[${now}] [DATOS DE PRUEBA] ${label} · Nombre: ${result.lead_name || "-"} · Email: ${result.lead_email || "-"} · Teléfono: ${result.lead_phone || "-"}`);
    }
    (result.stages || []).forEach((stage) => lines.push(`[${now}] [${stage.status === "PASS" ? "OK" : "ERROR"}] ${label} · ${stageLabels[stage.stage] || stage.stage}: ${stage.message}`));
  });
  if (running && (job.current_lead_name || job.current_lead_email || job.current_lead_phone)) {
    lines.push(`[${now}] [DATOS DE PRUEBA] Fila ${job.current_row || "?"} · ${job.current_program || "Sin programa"} · Nombre: ${job.current_lead_name || "-"} · Email: ${job.current_lead_email || "-"} · Teléfono: ${job.current_lead_phone || "-"}`);
  }
  if (running && job.last_error) lines.push(`[${now}] [ERROR] Último error · ${job.current_program || ""}: ${job.last_error}`);
  if (running) lines.push(`[${now}] [SISTEMA] Ejecutando la siguiente fila...`);
  renderTerminal(lines);
}

function renderStages(stages) {
  const list = document.querySelector("#leads-deploy-stages-list");
  if (!stages.length) {
    list.innerHTML = `<div class="bot-empty"><div class="empty-icon">◇</div><strong>El flujo todavia no se ha ejecutado</strong><span>Aqui aparecera el detalle de cada etapa en tiempo real.</span></div>`;
    return;
  }
  list.innerHTML = stages.map((stage) => {
    const ok = stage.status === "PASS";
    const stateLabel = ok ? "Completado" : "Error";
    return `<details class="utel-stage ${ok ? "success" : "error"}" ${ok ? "" : "open"}>
      <summary><span class="stage-marker">${escapeHtml(stage.step_number)}</span><span class="status-badge ${ok ? "success" : "error"}">${stateLabel}</span><strong>${escapeHtml(stageLabels[stage.stage] || stage.stage)}</strong><span>${escapeHtml(stage.message)}</span></summary>
      <div class="utel-stage-detail">
        <span>URL: ${escapeHtml(stage.url || "No disponible")}</span>
        <span>Selector: ${escapeHtml(stage.selector || "No aplica")}</span>
        <span>Screenshot: ${escapeHtml(stage.screenshot || "No generado")}</span>
      </div>
    </details>`;
  }).join("");
}

async function pollJob(showToast, statusApi, jobId) {
  try {
    const job = await statusApi(jobId);
    if (job.status === "RUNNING" || job.status === "QUEUED") {
      const status = document.querySelector("#leads-deploy-run-status");
      status.className = "bot-run-status running";
      status.innerHTML = `<strong>FLUJO EN SEGUNDO PLANO</strong><span>${escapeHtml(job.summary || "Playwright esta ejecutando UTEL e InConcert.")}</span><small>ID de ejecucion: ${escapeHtml(job.job_id)}</small>`;
      renderTerminal([`[${new Date().toLocaleTimeString("es-CO", { hour12: false })}] [SISTEMA] ${job.summary || "Ejecutando flujo UTEL/InConcert..."}`]);
      return;
    }
    window.clearInterval(state.pollTimer);
    state.pollTimer = null;
    state.activeJobId = null;
    localStorage.removeItem(ACTIVE_SINGLE_JOB_KEY);
    localStorage.setItem(LAST_SINGLE_JOB_KEY, jobId);
    document.querySelector("#leads-deploy-run").disabled = false;
    const stopButton = document.querySelector("#leads-deploy-stop");
    stopButton?.setAttribute("hidden", "");
    if (stopButton) {
      stopButton.disabled = false;
      stopButton.textContent = "Detener";
    }
    document.querySelector("#leads-deploy-run").classList.remove("loading");
    document.querySelector("#leads-deploy-run").innerHTML = "Ejecutar prueba <span>-></span>";
    if (job.status === "CANCELLED") {
      const status = document.querySelector("#leads-deploy-run-status");
      status.className = "bot-run-status";
      status.innerHTML = `<strong>EJECUCIÓN DETENIDA</strong><span>${escapeHtml(job.summary || "La tarea fue cancelada.")}</span>`;
      showToast("Ejecución detenida.", "info");
      return;
    }
    if (job.result) renderRunResult(job.result);
    if (job.result) renderErrorLog({
      job_id: job.job_id,
      completed: 1,
      total: 1,
      failed: job.result.status === "FAIL" ? 1 : 0,
      results: [{ row: { row_number: 1, level: job.result.level, country: job.result.country, form_type: job.result.form_type }, result: job.result }],
    });
    if (job.result) renderTerminal([
      `[DATOS DE PRUEBA] Nombre: ${job.result.lead_name || "-"} · Email: ${job.result.lead_email || "-"} · Teléfono: ${job.result.lead_phone || "-"}`,
      ...(job.result.stages || []).map((stage) => `[${stage.status === "PASS" ? "OK" : "ERROR"}] ${stageLabels[stage.stage] || stage.stage}: ${stage.message}`),
    ]);
    const completedAfterStop = Boolean(job.cancel_requested);
    const finalMessage = completedAfterStop
      ? (job.summary || "La fila activa se completó de forma segura.")
      : (job.status === "PASS" ? "Flujo UTEL/InConcert completado." : "El flujo UTEL/InConcert termino con errores.");
    showToast(finalMessage, job.status === "PASS" || completedAfterStop ? "info" : "error");
  } catch (error) {
    const status = document.querySelector("#leads-deploy-run-status");
    status.className = "bot-run-status error";
    const retryHint = error.status === 404
      ? "No se encontró temporalmente el registro del job en memoria del backend. Probablemente regresará al retomar la sesión."
      : "El trabajo continúa en el backend; la página volverá a consultar automáticamente.";
    status.innerHTML = `<strong>RECONECTANDO CON LA EJECUCIÓN</strong><span>${escapeHtml(error.message)}</span><small>${retryHint}</small>`;
  }
}

async function executeBot(showToast, runApi, statusApi) {
  if (state.activeJobId) {
    showToast("Ya hay un flujo UTEL/InConcert en ejecucion.", "error");
    return;
  }
  const config = validateConfig(showToast);
  if (!config) return;
  renderTerminal([`[${new Date().toLocaleTimeString("es-CO", { hour12: false })}] [SISTEMA] Iniciando una nueva ejecucion...`]);
  localStorage.setItem(STORAGE_KEY, JSON.stringify(config));

  const runButton = document.querySelector("#leads-deploy-run");
  const status = document.querySelector("#leads-deploy-run-status");
  runButton.disabled = true;
    const stopButton = document.querySelector("#leads-deploy-stop");
    stopButton?.removeAttribute("hidden");
    if (stopButton) {
      stopButton.disabled = false;
      stopButton.textContent = "Detener";
    }
  runButton.classList.add("loading");
  runButton.innerHTML = "<span>◌</span> Ejecutando...";
  status.className = "bot-run-status running";
  status.innerHTML = "<strong>INICIANDO FLUJO</strong><span>Validando configuracion y creando trabajo en segundo plano.</span>";

  try {
    const job = await runApi(config);
    if (job.lead_name && job.lead_email && job.lead_phone) {
      state.config.lead.name = job.lead_name;
      state.config.lead.email = job.lead_email;
      state.config.lead.phone = job.lead_phone;
      writeForm();
      localStorage.setItem(STORAGE_KEY, JSON.stringify(state.config));
      renderPreview();
      showToast(`Datos generados: ${job.lead_email}`, "info");
    }
    state.activeJobId = job.job_id;
    localStorage.setItem(ACTIVE_SINGLE_JOB_KEY, job.job_id);
    localStorage.removeItem(LAST_SINGLE_JOB_KEY);
    status.innerHTML = `<strong>FLUJO EN SEGUNDO PLANO</strong><span>Puedes seguir usando la app mientras se ejecuta.</span><small>ID de ejecucion: ${escapeHtml(job.job_id)}</small>`;
    state.pollTimer = window.setInterval(() => pollJob(showToast, statusApi, job.job_id), 1000);
    showToast("Flujo UTEL/InConcert iniciado.", "info");
  } catch (error) {
    status.className = "bot-run-status error";
    status.innerHTML = `<strong>NO SE PUDO EJECUTAR</strong><span>${escapeHtml(error.message)}</span>`;
    showToast(`No se pudo ejecutar: ${error.message}`, "error");
  } finally {
    if (!state.activeJobId) {
      runButton.disabled = false;
      runButton.classList.remove("loading");
      runButton.innerHTML = "Ejecutar prueba <span>-></span>";
    }
  }
}

export function initializeLeadsDeployModule({ showToast, runUtelInconcertBot, utelInconcertStatus, cancelUtelInconcert, previewBotSpreadsheet, runUtelBatch, utelBatchStatus, cancelUtelBatch }) {
  renderModuleShell();
  organizeBotForm();
  loadConfig();
  writeForm();
  renderPreview();
  renderStages([]);

  const headlessToggle = document.querySelector("#leads-deploy-headless");
  const keepBrowserOpenToggle = document.querySelector("#leads-deploy-keep-browser-open");
  const spreadsheetInput = document.querySelector("#leads-deploy-spreadsheet");
  const spreadsheetRow = document.querySelector("#leads-deploy-spreadsheet-row");
  const analyzeSpreadsheetButton = document.querySelector("#leads-deploy-analyze-spreadsheet");
  const batchButton = document.querySelector("#leads-deploy-batch-run");
  const retryErrorsButton = document.querySelector("#leads-deploy-retry-errors");
  const stopButton = document.querySelector("#leads-deploy-stop");
  const copyErrorsButton = document.querySelector("#leads-deploy-copy-errors");
  const downloadErrorsButton = document.querySelector("#leads-deploy-download-errors");
  let spreadsheetFile = null;
  let selectedMapping = {};
  let batchTimer = null;
  let activeBatchJobId = null;
  let importedRows = [];
  let lastFinishedBatch = null;

  const stopBatchPolling = () => {
    if (batchTimer) window.clearInterval(batchTimer);
    batchTimer = null;
  };

  const downloadBatchExcelAutomatically = (current, jobId) => {
    if (!current?.download_url || !jobId) return false;
    if (localStorage.getItem(AUTO_DOWNLOADED_BATCH_KEY) === jobId) return false;

    const apiBase = window.desktop?.apiUrl || window.location.origin;
    const anchor = document.createElement("a");
    anchor.href = `${apiBase}${current.download_url}`;
    anchor.download = "";
    anchor.style.display = "none";
    document.body.append(anchor);
    anchor.click();
    anchor.remove();

    localStorage.setItem(AUTO_DOWNLOADED_BATCH_KEY, jobId);
    return true;
  };

  const pollBatchJob = async (jobId, announceCompletion = true) => {
    try {
      const current = await utelBatchStatus(jobId);
      const running = current.status === "RUNNING" || current.status === "QUEUED";
      const liveError = current.last_error ? ` · Último error: fila ${current.current_row} (${current.current_program}): ${current.last_error}` : "";
      const phase = current.phase ? `${current.phase} · ` : "";
      const pendingCount = Number(current.pending || 0);
      const pendingLabel = pendingCount ? ` · Pendientes CRM: ${pendingCount}` : "";
      const progressText = `${phase}${current.dry_run ? "Dry run (sin envío)" : "Lote"}: ${current.completed}/${current.total} filas procesadas · OK: ${current.success} · Errores: ${current.failed}${pendingLabel}${liveError}`;
      const checkpointLink = current.download_url && Number(current.last_checkpoint_rows || 0) > 0
        ? ` <a href="${window.desktop?.apiUrl || window.location.origin}${current.download_url}" download>Descargar Excel acumulado (${current.last_checkpoint_rows} filas)</a>`
        : "";
      document.querySelector("#leads-deploy-run-status").innerHTML = `${escapeHtml(progressText)}${checkpointLink}`;
      renderBatchTerminal(current, running);
      renderErrorLog(current);

      if (running) return current;

      stopBatchPolling();
      activeBatchJobId = null;
      localStorage.removeItem(ACTIVE_BATCH_JOB_KEY);
      localStorage.setItem(LAST_BATCH_JOB_KEY, jobId);
      stopButton.hidden = true;
      stopButton.disabled = false;
      stopButton.textContent = "Detener";
      batchButton.disabled = false;
      document.querySelector("#leads-deploy-run").disabled = false;
      lastFinishedBatch = current;
      const failedRows = (current.results || []).filter((item) => item.result?.status === "FAIL");
      // Solo los fallos ocurridos antes del clic son seguros para reintentar.
      // Un resultado post-clic debe volver a consultarse en CRM, no reenviarse.
      const retriableRows = failedRows.filter(isSafeUtelRetry);
      const protectedRows = failedRows.length - retriableRows.length;
      retryErrorsButton.hidden = !spreadsheetFile || retriableRows.length === 0;
      retryErrorsButton.disabled = retriableRows.length === 0;
      retryErrorsButton.textContent = `Reintentar ${retriableRows.length} error${retriableRows.length === 1 ? "" : "es"} previo${retriableRows.length === 1 ? "" : "s"} al envío`;
      if (current.download_url) {
        const apiBase = window.desktop?.apiUrl || window.location.origin;
        const label = current.status === "PASS"
          ? (current.dry_run ? "Dry run completado (sin envío)" : "Lote completado")
          : (current.status === "CANCELLED" ? "Lote detenido de forma segura" : "Lote finalizado con resultados parciales");
        const protectedNotice = protectedRows
          ? ` ${protectedRows} fila${protectedRows === 1 ? "" : "s"} post-envío no se reintentará${protectedRows === 1 ? "" : "n"} para evitar duplicados.`
          : "";
        const finalPending = Number(current.pending || 0);
        const pendingNotice = finalPending
          ? ` ${finalPending} fila${finalPending === 1 ? "" : "s"} pendiente${finalPending === 1 ? "" : "s"} de verificación CRM.`
          : "";
        document.querySelector("#leads-deploy-run-status").innerHTML = `${label}: ${current.success} OK, ${current.failed} con error.${pendingNotice}${protectedNotice} <a href="${apiBase}${current.download_url}" download>Descargar Excel actualizado</a>`;
        renderBatchResults(current);
        const downloadedAutomatically = downloadBatchExcelAutomatically(current, jobId);
        if (announceCompletion) {
          showToast(
            downloadedAutomatically
              ? "Excel actualizado generado y descargado automáticamente."
              : "Excel actualizado generado correctamente.",
            "info"
          );
        }
      } else if (current.status === "CANCELLED") {
        setValidation(current.summary || "El lote fue detenido.");
        if (announceCompletion) showToast(current.summary || "El lote fue detenido.", "info");
      } else {
        setValidation(current.summary || "El lote terminó con errores.", "error");
        if (announceCompletion) showToast(current.summary || "El lote terminó con errores.", "error");
      }
      return current;
    } catch (error) {
      const status = document.querySelector("#leads-deploy-run-status");
      if (error.status === 404) {
        // El backend guarda jobs solo en memoria. Si se reinició, un ID que
        // quedó en localStorage ya no representa un lote recuperable.
        stopBatchPolling();
        if (activeBatchJobId === jobId) activeBatchJobId = null;
        if (localStorage.getItem(ACTIVE_BATCH_JOB_KEY) === jobId) localStorage.removeItem(ACTIVE_BATCH_JOB_KEY);
        if (localStorage.getItem(LAST_BATCH_JOB_KEY) === jobId) localStorage.removeItem(LAST_BATCH_JOB_KEY);
        stopButton.hidden = true;
        stopButton.disabled = false;
        stopButton.textContent = "Detener";
        batchButton.disabled = false;
        document.querySelector("#leads-deploy-run").disabled = false;
        status.className = "bot-run-status";
        const apiBase = window.desktop?.apiUrl || window.location.origin;
        status.innerHTML = `<strong>LOTE NO RECUPERABLE</strong><span>El backend se reinició y ya no conserva el estado en memoria.</span><a href="${apiBase}/api/bots/utel-inconcert/batch/${jobId}/download" download>Descargar Excel parcial, si ya fue generado</a><small>Los reportes guardados permanecen disponibles aunque el proceso se reinicie.</small>`;
        return null;
      }
      status.className = "bot-run-status error";
      status.innerHTML = `<strong>RECONECTANDO CON EL LOTE</strong><span>${escapeHtml(error.message)}</span><small>El trabajo continúa en el backend; la página volverá a consultar automáticamente.</small>`;
      return null;
    }
  };

  const watchBatchJob = async (jobId, { persist = true, announceCompletion = true } = {}) => {
    stopBatchPolling();
    activeBatchJobId = jobId;
    if (persist) {
      localStorage.setItem(ACTIVE_BATCH_JOB_KEY, jobId);
      localStorage.removeItem(LAST_BATCH_JOB_KEY);
    }
    stopButton.hidden = false;
    stopButton.disabled = false;
    stopButton.textContent = "Detener";
    batchButton.disabled = true;
    document.querySelector("#leads-deploy-run").disabled = true;
    await pollBatchJob(jobId, announceCompletion);
    if (activeBatchJobId === jobId) {
      batchTimer = window.setInterval(() => void pollBatchJob(jobId), 1000);
    }
  };

  const watchSingleJob = async (jobId, { announce = true } = {}) => {
    state.activeJobId = jobId;
    const runButton = document.querySelector("#leads-deploy-run");
    runButton.disabled = true;
    runButton.classList.add("loading");
    runButton.innerHTML = "<span>◌</span> Ejecutando...";
    stopButton.hidden = false;
    stopButton.disabled = false;
    stopButton.textContent = "Detener";
    await pollJob(announce ? showToast : () => {}, utelInconcertStatus, jobId);
    if (state.activeJobId === jobId) {
      state.pollTimer = window.setInterval(() => void pollJob(showToast, utelInconcertStatus, jobId), 1000);
    }
  };

  const restoreRememberedJob = async () => {
    const activeBatch = localStorage.getItem(ACTIVE_BATCH_JOB_KEY);
    if (activeBatch) {
      document.querySelector("#leads-deploy-run-status").innerHTML = "<strong>RECUPERANDO LOTE</strong><span>Consultando el progreso que continuó en segundo plano.</span>";
      await watchBatchJob(activeBatch, { persist: false, announceCompletion: false });
      if (activeBatchJobId === activeBatch) showToast("Ejecución por lote recuperada. Continúa en segundo plano.", "info");
      return;
    }

    const activeSingle = localStorage.getItem(ACTIVE_SINGLE_JOB_KEY);
    if (activeSingle) {
      document.querySelector("#leads-deploy-run-status").innerHTML = "<strong>RECUPERANDO EJECUCIÓN</strong><span>Consultando el progreso que continuó en segundo plano.</span>";
      await watchSingleJob(activeSingle, { announce: false });
      if (state.activeJobId === activeSingle) showToast("Ejecución recuperada. Continúa en segundo plano.", "info");
      return;
    }

    const lastBatch = localStorage.getItem(LAST_BATCH_JOB_KEY);
    if (lastBatch) {
      await watchBatchJob(lastBatch, { persist: false, announceCompletion: false });
      return;
    }

    const lastSingle = localStorage.getItem(LAST_SINGLE_JOB_KEY);
    if (lastSingle) await watchSingleJob(lastSingle, { announce: false });
  };
  copyErrorsButton.addEventListener("click", async () => {
    const content = document.querySelector("#leads-deploy-error-terminal")?.dataset.log || "";
    if (!content) return;
    try {
      await navigator.clipboard.writeText(content);
      showToast("Log de errores copiado. Ya puedes pegarlo en el chat.", "info");
    } catch (error) {
      showToast(`No se pudo copiar el log: ${error.message}`, "error");
    }
  });
  downloadErrorsButton.addEventListener("click", () => {
    const content = document.querySelector("#leads-deploy-error-terminal")?.dataset.log || "";
    if (!content) return;
    const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `errores-utel-${new Date().toISOString().replaceAll(":", "-")}.txt`;
    anchor.click();
    URL.revokeObjectURL(url);
    showToast("Log exclusivo de errores descargado.", "info");
  });
  const normalizeCountry = (value) => String(value || "").trim().toLocaleLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");
  const setMultiCountryMode = (enabled) => {
    const countryField = document.querySelector("#leads-deploy-country")?.closest("label, .field");
    if (countryField) countryField.classList.toggle("bot-internal-field", enabled);
    const sourceHint = document.querySelector('#view-leads-deploy [data-section="source"]')?.closest("section")?.querySelector(".bot-section-heading small");
    if (sourceHint) {
      sourceHint.textContent = enabled
        ? "Los países y casos se toman de cada fila del Excel"
        : "Selecciona el país y carga la fila del Excel";
    }
  };
  const applyImportedRow = (row, index = null) => {
    if (!row) return;
    if (index !== null) spreadsheetRow.value = String(index);
    if (row.country) setCountryValue(row.country);
    if (row.modality) document.querySelector("#leads-deploy-modality").value = row.modality;
    if (row.level) document.querySelector("#leads-deploy-level").value = row.level;
    if (row.utel_url) {
      document.querySelector("#leads-deploy-utel-url").value = row.utel_url;
      document.querySelector("#leads-deploy-utel-url-status").textContent = "URL UTEL cargada desde la fila seleccionada del Excel.";
    }
    if (row.inconcert_url) document.querySelector("#leads-deploy-inconcert-url").value = row.inconcert_url;
    if (row.program_name) document.querySelector("#leads-deploy-program-name").value = row.program_name;
    if (row.form_type) {
      const location = row.form_type.toLowerCase();
      document.querySelector("#leads-deploy-form-type").value = location.includes("tarjeta") ? "tarjeta" : location.includes("footer") ? "footer" : "lateral";
    }
  };
  const renderColumnMapping = (headers, autoMapping = {}) => {
    const container = document.querySelector("#leads-deploy-column-mapping");
    const optionList = ['<option value="">Selecciona una columna</option>', ...headers.map((header) => `<option value="${escapeHtml(header)}">${escapeHtml(header)}</option>`)].join("");
    const findHeader = (key, fallback = "") => autoMapping[key] || headers.find((header) => normalizeCountry(header) === normalizeCountry(fallback)) || "";
    selectedMapping = {
      program_name: findHeader("program_name", "Programa"),
      modality: findHeader("modality", "Modalidad"),
      level: findHeader("level", "Nivel"),
      country: findHeader("country", "Country") || headers.find((header) => normalizeCountry(header) === "locale"),
      utel_url: findHeader("utel_url", "URL"),
      form_type: findHeader("form_type", "Location"),
      inconcert_url: findHeader("inconcert_url", "inconcert/balanceador") || findHeader("inconcert_url", "Url inconcert/balanceador"),
      lead_origin_url: findHeader("lead_origin_url", "Url Origen Lead"),
      lead_url: findHeader("lead_url", "URL LEAD") || "URL LEAD",
    };
    const isDeployValidation = !selectedMapping.program_name
      && Boolean(selectedMapping.level && selectedMapping.country && selectedMapping.form_type && selectedMapping.utel_url);
    selectedMapping.workflow_mode = isDeployValidation ? "form_validation" : "product_release";
    state.workflowMode = selectedMapping.workflow_mode;
    setMultiCountryMode(isDeployValidation);
    container.innerHTML = `<div class="mapping-title">Columnas a utilizar</div><div class="mapping-grid">
      <label><span>Programa *</span><select id="leads-deploy-map-program">${optionList}</select></label>
      <label><span>Modalidad</span><select id="leads-deploy-map-modality">${optionList}</select></label>
      <label><span>Nivel (alternativa)</span><select id="leads-deploy-map-level">${optionList}</select></label>
      <label><span>País (Locale/Country)</span><select id="leads-deploy-map-country">${optionList}</select></label>
      <label><span>URL *</span><select id="leads-deploy-map-url">${optionList}</select></label>
      <label><span>Formulario</span><select id="leads-deploy-map-form">${optionList}</select></label>
      <label><span>InConcert</span><select id="leads-deploy-map-inconcert">${optionList}</select></label>
      <label><span>Origen lead</span><select id="leads-deploy-map-origin">${optionList}</select></label>
      <label><span>Salida URL LEAD</span><select id="leads-deploy-map-lead">${optionList}<option value="URL LEAD">Crear columna URL LEAD</option></select></label>
    </div><small>Se detectaron ${headers.length} columnas. Puedes cambiar la selección manualmente.</small>`;
    document.querySelector("#leads-deploy-map-program").value = selectedMapping.program_name;
    document.querySelector("#leads-deploy-map-modality").value = selectedMapping.modality;
    document.querySelector("#leads-deploy-map-level").value = selectedMapping.level;
    document.querySelector("#leads-deploy-map-country").value = selectedMapping.country;
    document.querySelector("#leads-deploy-map-url").value = selectedMapping.utel_url;
    document.querySelector("#leads-deploy-map-form").value = selectedMapping.form_type;
    document.querySelector("#leads-deploy-map-inconcert").value = selectedMapping.inconcert_url;
    document.querySelector("#leads-deploy-map-origin").value = selectedMapping.lead_origin_url;
    document.querySelector("#leads-deploy-map-lead").value = selectedMapping.lead_url || "URL LEAD";
    if (isDeployValidation) {
      ["leads-deploy-map-program", "leads-deploy-map-modality", "leads-deploy-map-lead"].forEach((id) => {
        document.querySelector(`#${id}`)?.closest("label")?.classList.add("bot-internal-field");
      });
      document.querySelector("#leads-deploy-map-level")?.closest("label")?.querySelector("span")?.replaceChildren("Nivel *");
      document.querySelector("#leads-deploy-map-inconcert")?.closest("label")?.querySelector("span")?.replaceChildren("InConcert/balanceador (opcional)");
      container.querySelector("small").textContent = "Flujo detectado: validacion de formularios por pais. Se reconocio la columna InConcert/balanceador; el Excel de salida incluira resultado y detalle.";
    }
    const updateAutomaticFields = () => {
      const visibility = {
        "leads-deploy-modality": isDeployValidation || Boolean(selectedMapping.modality),
        "leads-deploy-form-type": isDeployValidation || Boolean(selectedMapping.form_type),
        "leads-deploy-program-strategy": true,
        "leads-deploy-program-name": true,
        "leads-deploy-inconcert-url": true,
      };
      Object.entries(visibility).forEach(([id, hidden]) => document.querySelector(`#${id}`)?.closest("label, .field")?.classList.toggle("bot-internal-field", hidden));
    };
    updateAutomaticFields();
    ["program", "modality", "level", "country", "url", "form", "inconcert", "origin", "lead"].forEach((key) => document.querySelector(`#leads-deploy-map-${key}`).addEventListener("change", () => {
      const selectedRow = selectedMapping.selected_row_number;
      const selectedSheet = selectedMapping.selected_sheet;
      selectedMapping = { program_name: document.querySelector("#leads-deploy-map-program").value, modality: document.querySelector("#leads-deploy-map-modality").value, level: document.querySelector("#leads-deploy-map-level").value, country: document.querySelector("#leads-deploy-map-country").value, utel_url: document.querySelector("#leads-deploy-map-url").value, form_type: document.querySelector("#leads-deploy-map-form").value, inconcert_url: document.querySelector("#leads-deploy-map-inconcert").value, lead_origin_url: document.querySelector("#leads-deploy-map-origin").value, lead_url: document.querySelector("#leads-deploy-map-lead").value, workflow_mode: isDeployValidation ? "form_validation" : "product_release" };
      if (selectedRow !== undefined) selectedMapping.selected_row_number = selectedRow;
      if (selectedSheet !== undefined) selectedMapping.selected_sheet = selectedSheet;
      updateAutomaticFields();
    }));
  };
  const analyzeSpreadsheetFile = async (file) => {
    if (!previewBotSpreadsheet) {
      const message = "El API de preview de Excel no está disponible.";
      document.querySelector("#leads-deploy-spreadsheet-status").textContent = `No se pudo analizar el Excel: ${message}`;
      showToast(message, "error");
      return;
    }
    if (!file) return;
    spreadsheetFile = file;
    analyzeSpreadsheetButton.disabled = true;
    analyzeSpreadsheetButton.textContent = "Analizando...";
    document.querySelector("#leads-deploy-spreadsheet-status").textContent = "Analizando hojas, columnas y filas...";
    try {
      const preview = await previewBotSpreadsheet(file);
      if (!preview || !Array.isArray(preview.sheets)) {
        throw new Error("La respuesta de análisis del Excel no tiene el formato esperado.");
      }
      importedRows = preview.sheets.flatMap((sheet) => sheet.rows.map((row) => ({ ...row, sheet: sheet.name })));
      spreadsheetRow.innerHTML = '<option value="">Selecciona una fila</option>' + importedRows.map((row, index) => `<option value="${index}">${escapeHtml(row.sheet)} - fila ${row.row_number} - ${escapeHtml(row.program_name || row.level || row.utel_url || "sin nombre")}</option>`).join("");
      const firstSheet = preview.sheets[0];
      const allHeaders = [...new Set(preview.sheets.flatMap((sheet) => sheet.headers))];
      if (firstSheet) renderColumnMapping(allHeaders, firstSheet.mapping);
      batchButton.hidden = true;
      document.querySelector("#leads-deploy-run").textContent = selectedMapping.workflow_mode === "form_validation" ? "Ejecutar todos los casos" : "Ejecutar todos los programas";
      const currentCountry = normalizeCountry(document.querySelector("#leads-deploy-country").value);
      void currentCountry;
      document.querySelector("#leads-deploy-spreadsheet-status").textContent = `Excel analizado: ${allHeaders.length} columnas y ${importedRows.length} filas.${selectedMapping.workflow_mode === "form_validation" ? " Flujo Leads Deploy detectado." : ""}`;
      showToast("Excel analizado. Confirma las columnas y selecciona la fila.", "info");
    } catch (error) {
      setMultiCountryMode(false);
      const message = error?.message || "Respuesta inválida del backend.";
      document.querySelector("#leads-deploy-spreadsheet-status").textContent = `No se pudo analizar el Excel: ${message}`;
      showToast(`No se pudo analizar el Excel: ${message}`, "error");
    } finally {
      analyzeSpreadsheetButton.disabled = false;
      analyzeSpreadsheetButton.textContent = "Analizar Excel";
    }
  };

  spreadsheetInput.addEventListener("change", async () => {
      const file = spreadsheetInput.files[0];
    if (!file || !previewBotSpreadsheet) return;
    spreadsheetFile = file;
    lastFinishedBatch = null;
    retryErrorsButton.hidden = true;
    if (spreadsheetInput.dataset.requestAnalyze !== "true") {
      importedRows = [];
      selectedMapping = {};
      state.workflowMode = "product_release";
      setMultiCountryMode(false);
      document.querySelector("#leads-deploy-column-mapping").innerHTML = "";
      batchButton.hidden = true;
      document.querySelector("#leads-deploy-spreadsheet-status").textContent = `Archivo listo: ${file.name}. Pulsa Analizar Excel para confirmar las columnas.`;
      return;
    }
    delete spreadsheetInput.dataset.requestAnalyze;
    try {
      const preview = await previewBotSpreadsheet(file);
      importedRows = preview.sheets.flatMap((sheet) => sheet.rows.map((row) => ({ ...row, sheet: sheet.name })));
      spreadsheetRow.innerHTML = '<option value="">Selecciona una fila</option>' + importedRows.map((row, index) => `<option value="${index}">${escapeHtml(row.sheet)} · fila ${row.row_number} · ${escapeHtml(row.program_name || row.level || row.utel_url || "sin nombre")}</option>`).join("");
      const fileSize = file.size > 1024 * 1024 ? `${(file.size / (1024 * 1024)).toFixed(1)} MB` : `${Math.max(1, Math.round(file.size / 1024))} KB`;
      document.querySelector("#leads-deploy-spreadsheet-status").textContent = `✓ ${file.name} · ${fileSize} · Archivo cargado`;
      const firstSheet = preview.sheets[0];
      const allHeaders = [...new Set(preview.sheets.flatMap((sheet) => sheet.headers))];
      if (firstSheet) renderColumnMapping(allHeaders, firstSheet.mapping);
      batchButton.hidden = true;
      showToast("Excel analizado. Selecciona la fila que deseas ejecutar.", "info");
    } catch (error) {
      showToast(`No se pudo analizar el Excel: ${error.message}`, "error");
    }
  });
  analyzeSpreadsheetButton.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    if (!spreadsheetInput.files[0]) {
      spreadsheetInput.dataset.requestAnalyze = "true";
      spreadsheetInput.value = "";
      spreadsheetInput.click();
      showToast("Selecciona primero un archivo .xlsx.", "error");
      return;
    }
    analyzeSpreadsheetButton.disabled = true;
    analyzeSpreadsheetButton.textContent = "Analizando...";
    document.querySelector("#leads-deploy-spreadsheet-status").textContent = "Analizando hojas, columnas y filas...";
    void analyzeSpreadsheetFile(spreadsheetInput.files[0]);
  });
  const executeBatch = async (mappingOverride = null, retryCount = 0) => {
    if (!spreadsheetFile || !runUtelBatch) return;
    readForm();
    const mappingToRun = mappingOverride || selectedMapping;
    if (!(mappingToRun.program_name || mappingToRun.level) || !mappingToRun.utel_url) {
      showToast("Selecciona Programa o Nivel, además de la columna URL.", "error");
      return;
    }
    const runButton = document.querySelector("#leads-deploy-run");
    renderTerminal([`[${new Date().toLocaleTimeString("es-CO", { hour12: false })}] [SISTEMA] Iniciando una nueva ejecucion por lote...`]);
    renderErrorLog({ results: [] });
    batchButton.disabled = true;
    retryErrorsButton.hidden = true;
    runButton.disabled = true;
    setValidation(retryCount
      ? `Reintento iniciado: se procesarán únicamente ${retryCount} fila${retryCount === 1 ? "" : "s"} con error.`
      : (state.config.dry_run ? "Dry run iniciado: se rellenarán las filas sin enviar leads." : "Lote iniciado. Se procesarán las filas una por una."), "success");
    try {
      const job = await runUtelBatch(spreadsheetFile, state.config, mappingToRun);
      await watchBatchJob(job.job_id);
    } catch (error) {
      batchButton.disabled = false;
      document.querySelector("#leads-deploy-run").disabled = false;
      setValidation(error.message, "error");
      showToast(error.message, "error");
    }
  };
  batchButton.addEventListener("click", executeBatch);
  retryErrorsButton.addEventListener("click", () => {
    const failedRows = (lastFinishedBatch?.results || [])
      .filter(isSafeUtelRetry)
      .map((item) => ({ sheet: item.row?.sheet, row_number: item.row?.row_number }))
      .filter((row) => row.sheet && Number.isInteger(Number(row.row_number)));
    if (!spreadsheetFile || !failedRows.length) {
      showToast("No hay filas fallidas disponibles para reintentar. Vuelve a cargar el Excel si reiniciaste la página.", "error");
      return;
    }
    const retryMapping = { ...selectedMapping, selected_rows: failedRows };
    delete retryMapping.selected_sheet;
    delete retryMapping.selected_row_number;
    void executeBatch(retryMapping, failedRows.length);
  });
  stopButton.addEventListener("click", async () => {
    let requestAccepted = false;
    try {
      stopButton.disabled = true;
      stopButton.textContent = "Deteniendo...";
      if (activeBatchJobId && cancelUtelBatch) {
        await cancelUtelBatch(activeBatchJobId);
      } else if (state.activeJobId && cancelUtelInconcert) {
        await cancelUtelInconcert(state.activeJobId);
      } else {
        throw new Error("No hay una ejecución activa para detener.");
      }
      requestAccepted = true;
      document.querySelector("#leads-deploy-run-status").textContent = "Deteniendo ejecución y cerrando el navegador...";
      appendTerminal([`[${new Date().toLocaleTimeString("es-CO", { hour12: false })}] [DETENCIÓN] Cancelando la tarea activa.`]);
      showToast("Detención solicitada. Esperando el cierre de la tarea.", "info");
    } catch (error) {
      showToast(`No se pudo detener la ejecución: ${error.message}`, "error");
    } finally {
      if (!requestAccepted) {
        stopButton.disabled = false;
        stopButton.textContent = "Detener";
      }
    }
  });
  spreadsheetRow.addEventListener("change", () => {
    const row = importedRows[Number(spreadsheetRow.value)];
    if (row) {
      selectedMapping.selected_row_number = row.row_number;
      selectedMapping.selected_sheet = row.sheet;
    } else {
      delete selectedMapping.selected_row_number;
      delete selectedMapping.selected_sheet;
    }
    const runButton = document.querySelector("#leads-deploy-run");
    const label = row ? "Ejecutar fila seleccionada" : (selectedMapping.workflow_mode === "form_validation" ? "Ejecutar todos los casos" : "Ejecutar todos los programas");
    runButton.textContent = label;
    batchButton.textContent = row ? "Ejecutar fila seleccionada" : "Ejecutar todas las filas";
    applyImportedRow(row, Number.isNaN(Number(spreadsheetRow.value)) ? null : Number(spreadsheetRow.value));
    if (!row) return;
    if (row.country) setCountryValue(row.country);
    if (row.level) document.querySelector("#leads-deploy-level").value = row.level;
    if (row.utel_url) document.querySelector("#leads-deploy-utel-url").value = row.utel_url;
    if (row.inconcert_url) document.querySelector("#leads-deploy-inconcert-url").value = row.inconcert_url;
    if (row.program_name) document.querySelector("#leads-deploy-program-name").value = row.program_name;
    if (row.form_type) {
      const location = row.form_type.toLowerCase();
      document.querySelector("#leads-deploy-form-type").value = location.includes("tarjeta") ? "tarjeta" : location.includes("footer") ? "footer" : "lateral";
    }
  });
  // El país no selecciona filas automáticamente: una fila elegida es explícita;
  // si el selector queda vacío, el lote representa todos los programas.
  if (keepBrowserOpenToggle.checked) headlessToggle.checked = false;
  keepBrowserOpenToggle.addEventListener("change", () => {
    if (keepBrowserOpenToggle.checked) headlessToggle.checked = false;
  });
  headlessToggle.addEventListener("change", () => {
    if (headlessToggle.checked) keepBrowserOpenToggle.checked = false;
  });

  document.querySelector("#leads-deploy-save").addEventListener("click", () => saveConfig(showToast));
  document.querySelector("#leads-deploy-validate").addEventListener("click", () => validateConfig(showToast));
  document.querySelector("#leads-deploy-run").addEventListener("click", () => {
    if (spreadsheetFile) {
      if (!importedRows.length) {
        showToast("Analiza primero el Excel para ejecutar sus programas.", "error");
        return;
      }
      void executeBatch();
      return;
    }
    executeBot(showToast, runUtelInconcertBot, utelInconcertStatus);
  });
  document.querySelector("#leads-deploy-guide").addEventListener("click", () => showToast("1. Selecciona el pais. 2. Carga el Excel y elige una fila. 3. Confirma modalidad y nivel. 4. Ejecuta la prueba. Usa Dry run para validar sin enviar.", "info"));
  document.querySelector("#leads-deploy-clear").addEventListener("click", () => {
    localStorage.removeItem(STORAGE_KEY);
    state.workflowMode = "product_release";
    setMultiCountryMode(false);
    state.config = {
      name: "Bot Leads Deploy",
      environment: "sandbox",
      dry_run: true,
      country: "ecuador",
      utel_url: "",
      inconcert_url: "",
      modality: "En linea",
      level: "Licenciatura",
      form_type: "lateral",
      program_selection_strategy: "first",
      program_name: "",
      submit_success_pattern: "Env\u00edo correcto|Pronto recibir\u00e1s informaci\u00f3n",
      submit_error_pattern: "Error al enviar|Contacta a soporte|error|invalido|inválido|obligatorio|requerido|fall",
      browser: "chromium",
      headless: true,
      keep_browser_open: false,
      lead: { name: "pending", email: "pending@testingUtel.com", phone: "900000000" },
    };
    writeForm();
    renderPreview();
    renderStages([]);
    renderErrorLog({ results: [] });
    document.querySelector("#leads-deploy-summary").innerHTML = "";
    setValidation("Completa la configuracion para validar el flujo UTEL/InConcert.");
    showToast("Configuracion limpiada.", "info");
  });
  void restoreRememberedJob();
}
