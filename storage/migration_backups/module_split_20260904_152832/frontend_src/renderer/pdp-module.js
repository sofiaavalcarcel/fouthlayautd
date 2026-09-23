"use strict";

// Controlador PDP: carga de fuentes y representación segura de hallazgos.
function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function sectionClass(status) {
  return { PASS: "pass", WARNING: "warning", FAIL: "fail", NO_DISPONIBLE: "na" }[status] || "na";
}

function sectionLabel(status) {
  return { PASS: "Coincide", WARNING: "Revisar", FAIL: "No coincide", NO_DISPONIBLE: "Sin referencia" }[status] || "No disponible";
}

function programStatusClass(status) {
  return { PASS: "success", WARNING: "warning", ERROR: "error" }[status] || "pending";
}

function fileDescription(file, extension) {
  if (!file) return `Aún no has seleccionado un ${extension}.`;
  const size = file.size < 1024 * 1024 ? `${Math.ceil(file.size / 1024)} KB` : `${(file.size / (1024 * 1024)).toFixed(1)} MB`;
  return `${file.name} · ${size}`;
}

function renderSection(name, section) {
  const coverage = section.status === "NO_DISPONIBLE" ? "Sin sección" : `${section.coverage ?? 0}% de coincidencia`;
  return `<div class="pdp-section ${sectionClass(section.status)}"><strong>${name}</strong><span>${sectionLabel(section.status)} · ${coverage}</span></div>`;
}

function renderProgram(program) {
  const sections = [
    ["Título", program.title],
    ["Descripción", program.description],
    ["Asignaturas", program.subjects],
    ["FAQ", program.faqs],
  ];
  const missing = sections.flatMap(([name, section]) => (section.missing || []).map((item) => `${name}: ${item}`));
  return `<article class="pdp-program-result">
    <div class="pdp-program-header">
      <div><strong>${escapeHtml(program.program)}</strong><a href="${escapeHtml(program.url)}" target="_blank" rel="noreferrer">${escapeHtml(program.url)}</a></div>
      <span class="status-badge ${programStatusClass(program.status)}">${escapeHtml(program.status)}</span>
    </div>
    <div class="pdp-section-grid">${sections.map(([name, section]) => renderSection(name, section)).join("")}</div>
    <details><summary>${escapeHtml(program.message)}</summary>${missing.length ? `<ul class="pdp-missing">${missing.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>` : "<span>Sin diferencias destacadas para este programa.</span>"}</details>
  </article>`;
}

function renderResult(result) {
  const status = document.querySelector("#pdp-run-status");
  const summary = document.querySelector("#pdp-summary");
  const list = document.querySelector("#pdp-results-list");
  const count = document.querySelector("#pdp-result-count");
  const data = result.summary;
  const hasDifferences = data.failed || data.errors || data.warnings;

  status.className = `pdp-run-status ${hasDifferences ? "warning" : "success"}`;
  status.textContent = hasDifferences
    ? `Validación terminada. Hay diferencias o programas que necesitan revisión.`
    : "Validación terminada. Todas las secciones detectadas coinciden.";
  count.textContent = `${data.programs} ${data.programs === 1 ? "PDP" : "PDPs"}`;
  summary.innerHTML = [
    [data.programs, "PDPs revisadas"],
    [data.passed, "Sin diferencias"],
    [data.failed, "Secciones a revisar"],
    [data.errors, "Errores de URL"],
  ].map(([value, label]) => `<div class="pdp-summary-card"><strong>${escapeHtml(value)}</strong><span>${label}</span></div>`).join("");
  list.innerHTML = result.programs.map(renderProgram).join("");
}

function renderSemanticFinding(finding) {
  const labels = { MATCH_EXACTO: "MATCH EXACTO", MATCH_NORMALIZADO: "MATCH NORMALIZADO", DIFERENTE: "DIFERENTE", FALTANTE: "FALTANTE", EXTRA: "EXTRA", DUPLICADO: "DUPLICADO", POSIBLE_COINCIDENCIA: "POSIBLE COINCIDENCIA", REVISION_MANUAL: "REVISIÓN MANUAL" };
  const className = { MATCH_EXACTO: "success", MATCH_NORMALIZADO: "success", DIFERENTE: "warning", FALTANTE: "error", EXTRA: "warning", DUPLICADO: "warning", POSIBLE_COINCIDENCIA: "warning", REVISION_MANUAL: "warning" }[finding.status] || "pending";
  return `<details class="pdp-semantic-finding ${className}" open><summary><span class="status-badge ${className}">${labels[finding.status] || escapeHtml(finding.status)}</span><strong>${escapeHtml(finding.section || "Sin sección")}</strong><span>${escapeHtml(finding.expected || finding.actual)}</span></summary><div class="pdp-finding-detail"><div><b>Esperado</b><p>${escapeHtml(finding.expected || "No existe en el documento")}</p></div><div><b>Encontrado</b><p>${escapeHtml(finding.actual || "No encontrado")}</p></div><small>Confianza: ${Math.round((finding.confidence || 0) * 100)}% · ${escapeHtml(finding.reason || "")}</small></div></details>`;
}

function renderSemanticResult(result) {
  const summary = document.querySelector("#pdp-semantic-summary");
  const list = document.querySelector("#pdp-semantic-results");
  const status = document.querySelector("#pdp-semantic-status");
  const data = result.summary || {};
  const cards = [[data.sections, "Secciones"], [data.exact_matches, "Match exacto"], [data.normalized_matches, "Normalizados"], [data.different, "Diferentes"], [data.missing, "Faltantes"], [data.extra, "Extras"], [data.possible_matches, "Posibles"], [data.manual_review, "Revisión manual"]];
  summary.innerHTML = cards.map(([value, label]) => `<div class="pdp-summary-card"><strong>${escapeHtml(value ?? 0)}</strong><span>${label}</span></div>`).join("");
  status.className = `pdp-run-status ${result.status === "PASS" ? "success" : "warning"}`;
  const ai = result.ai || {};
  const successfulProvider = ai.successful_provider ? ` Proveedor usado: ${ai.successful_provider}.` : "";
  const fallbackNotice = ai.fallback_mode === "deterministic" ? " Las IAs no estuvieron disponibles; se usó el comparador sin IA y los casos ambiguos requieren revisión manual." : "";
  status.textContent = result.status === "PASS" ? `Verificación completada: no se detectaron diferencias.${successfulProvider}` : `Verificación completada: revisa los hallazgos antes de tomar una decisión.${successfulProvider}${fallbackNotice}`;
  list.innerHTML = result.findings?.length ? result.findings.map(renderSemanticFinding).join("") : `<div class="bot-empty"><strong>No se encontraron diferencias.</strong><span>La página coincide con el documento en los elementos extraídos.</span></div>`;
}

export function initializePdpModule({ showToast, validatePdp, validatePdpSemantic }) {
  const excelInput = document.querySelector("#pdp-excel-file");
  const docxInput = document.querySelector("#pdp-docx-file");
  const excelName = document.querySelector("#pdp-excel-name");
  const docxName = document.querySelector("#pdp-docx-name");
  const runButton = document.querySelector("#pdp-run");
  const status = document.querySelector("#pdp-run-status");

  excelInput.addEventListener("change", () => {
    excelName.textContent = fileDescription(excelInput.files[0], "Excel");
  });
  docxInput.addEventListener("change", () => {
    docxName.textContent = fileDescription(docxInput.files[0], "DOCX");
  });

  runButton.addEventListener("click", async () => {
    const excelFile = excelInput.files[0];
    const docxFile = docxInput.files[0];
    if (!excelFile || !docxFile) {
      showToast("Selecciona el Excel y el DOCX antes de ejecutar la comparación.", "error");
      return;
    }
    if (!excelFile.name.toLowerCase().endsWith(".xlsx") || !docxFile.name.toLowerCase().endsWith(".docx")) {
      showToast("Los archivos deben tener extensiones .xlsx y .docx.", "error");
      return;
    }

    runButton.disabled = true;
    runButton.classList.add("loading");
    status.className = "pdp-run-status running";
    status.textContent = "Leyendo fuentes y revisando las páginas PDP. El tiempo depende de la cantidad de URLs.";
    try {
      const result = await validatePdp(excelFile, docxFile);
      renderResult(result);
      showToast("Validación de PDP terminada. Revisa las diferencias marcadas.", "info");
    } catch (error) {
      status.className = "pdp-run-status error";
      status.textContent = error.message;
      showToast(`No se pudo validar las PDP: ${error.message}`, "error");
    } finally {
      runButton.disabled = false;
      runButton.classList.remove("loading");
    }
  });

  const sourceInput = document.querySelector("#pdp-source-file");
  const sourceName = document.querySelector("#pdp-source-name");
  const pageUrl = document.querySelector("#pdp-page-url");
  const useAi = document.querySelector("#pdp-use-ai");
  const semanticRun = document.querySelector("#pdp-semantic-run");
  const semanticStatus = document.querySelector("#pdp-semantic-status");
  sourceInput.addEventListener("change", () => { sourceName.textContent = fileDescription(sourceInput.files[0], "documento"); });
  semanticRun.addEventListener("click", async () => {
    const sourceFile = sourceInput.files[0];
    if (!sourceFile || !pageUrl.value.trim()) {
      showToast("Selecciona un documento y escribe la URL antes de comparar.", "error");
      return;
    }
    semanticRun.disabled = true;
    semanticRun.classList.add("loading");
    semanticStatus.className = "pdp-run-status running";
    semanticStatus.textContent = "Extrayendo la estructura del documento y de la página. Puede tardar unos segundos...";
    try {
      const result = await validatePdpSemantic(sourceFile, pageUrl.value.trim(), useAi.checked);
      renderSemanticResult(result);
      showToast("Comparación genérica terminada.", "info");
    } catch (error) {
      semanticStatus.className = "pdp-run-status error";
      semanticStatus.textContent = error.message;
      showToast(`No se pudo comparar: ${error.message}`, "error");
    } finally {
      semanticRun.disabled = false;
      semanticRun.classList.remove("loading");
    }
  });
}
