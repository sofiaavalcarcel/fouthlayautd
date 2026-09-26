"use strict";

function escapeHtml(value) {
  return String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
}

function humanizeProcessError(value) {
  const message = String(value ?? "");
  if (message.includes("cannot access local variable")) return "Error interno al preparar los datos actuales del producto. El proceso fue detenido sin guardar cambios incompletos.";
  return message;
}

function renderResults(job) {
  const results = job.results || [];
  const errorsBox = document.querySelector("#strapi-products-errors");
  const errorStatuses = new Set(["FAILED", "NOT_FOUND", "AMBIGUOUS", "INVALID_DATA"]);
  const errors = results.filter((item) => errorStatuses.has(item.status) || item.verification?.ok === false);
  const diagnostics = results.flatMap((item) => (item.diagnostics || []).map((diagnostic) => ({ ...diagnostic, program: diagnostic.program || item.program })));
  const generalErrors = job.general_errors || [];
  const fallbackErrors = errors
    .filter((item) => !(item.diagnostics || []).length)
    .map((item) => ({
      program: item.program,
      section: "proceso del producto",
      field: "general",
      message: item.message || "No se pudo completar este producto.",
      explanation: "El producto terminó con estado de error.",
      action: "Revisa el detalle y reintenta únicamente este producto.",
      severity: "error",
    }));
  const allDiagnostics = [...diagnostics, ...fallbackErrors];
  const diagnosticMarkup = (item) => `<li><b>${escapeHtml(item.program || "Producto sin nombre")}</b> · <b>${escapeHtml(item.section || "sección no indicada")}</b>${item.field ? ` · <b>${escapeHtml(item.field)}</b>` : ""}<br><span>${escapeHtml(item.message || "Sin detalle")}</span>${item.explanation ? `<small>Qué significa: ${escapeHtml(item.explanation)}</small>` : ""}${item.action ? `<small>Qué hacer: ${escapeHtml(item.action)}</small>` : ""}</li>`;
  if (errorsBox) {
    const errorDiagnostics = allDiagnostics.filter((item) => item.severity !== "warning");
    const infoDiagnostics = allDiagnostics.filter((item) => item.severity === "info");
    const realErrors = errorDiagnostics.filter((item) => item.severity !== "info");
    const warnings = allDiagnostics.filter((item) => item.severity === "warning");
    errorsBox.hidden = generalErrors.length === 0 && realErrors.length === 0 && infoDiagnostics.length === 0 && warnings.length === 0;
    errorsBox.innerHTML = [
      generalErrors.length ? `<strong>Errores generales</strong><ul>${generalErrors.map(diagnosticMarkup).join("")}</ul>` : "",
      realErrors.length ? `<strong>Errores encontrados</strong><ul>${realErrors.map(diagnosticMarkup).join("")}</ul>` : "",
      infoDiagnostics.length ? `<strong>Información ausente en el documento</strong><ul>${infoDiagnostics.map(diagnosticMarkup).join("")}</ul>` : "",
      warnings.length ? `<strong>Advertencias</strong><ul>${warnings.map(diagnosticMarkup).join("")}</ul>` : "",
    ].join("");
  }
  const summary = { ...(job.summary || {}) };
  if (results.some((item) => item.verification)) {
    summary.productos_verificados = results.filter((item) => item.verification?.ok === true).length;
    summary.fallos_verificacion = results.filter((item) => item.verification?.ok === false).length;
    summary.cambios_propuestos_o_aplicados = results.reduce((total, item) => total + (item.changes?.length || 0), 0);
    summary.diagnosticos = allDiagnostics.length;
    summary.campos_conservados = results.reduce((total, item) => total + (item.preserved_fields?.length || 0), 0);
  }
  const summaryLabels = { total: "Productos", updated: "Actualizados", dry_run: "Dry run", skipped: "Sin cambios", not_found: "No encontrados", ambiguous: "Ambiguos", invalid_data: "Datos inválidos", failed: "Fallidos", productos_verificados: "Verificados", fallos_verificacion: "Fallos de verificación", cambios_propuestos_o_aplicados: "Cambios", pdp_procesados: "PDP procesados", diagnosticos: "Diagnósticos", campos_conservados: "Campos conservados" };
  document.querySelector("#strapi-products-summary").innerHTML = Object.entries(summary).map(([key, value]) => `<div class="pdp-summary-card"><strong>${escapeHtml(value)}</strong><span>${escapeHtml(summaryLabels[key] || key)}</span></div>`).join("");
  document.querySelector("#strapi-products-results").innerHTML = results.map((item) => {
    const verification = item.verification || {};
    const verificationLabel = item.status === "DRY_RUN" ? "Dry run · sin escritura" : verification.ok === true ? "Verificado" : verification.ok === false ? "Falló verificación" : "No verificado";
    const changes = (item.changes || []).map((change) => `<div class="strapi-change-row"><strong>${escapeHtml(change.field)}</strong><span>${escapeHtml(change.action || "update")} · ${change.verified === true ? "verificado" : change.verified === false ? "no coincide" : "sin verificación"}</span><small>Antes: ${escapeHtml(JSON.stringify(change.before ?? null))}</small><small>Después: ${escapeHtml(JSON.stringify(change.after ?? null))}</small>${change.created_id != null ? `<small>ID creado: ${escapeHtml(change.created_id)}</small>` : ""}</div>`).join("");
    const preserved = item.preserved_fields?.length ? `<small><b>Conservados:</b> ${escapeHtml(item.preserved_fields.join(", "))}</small>` : "";
    const sourceList = Object.entries(item.sources || {}).filter(([, value]) => value).map(([key, value]) => `${key}: ${value}`).join(" · ");
    const warnings = (item.diagnostics || []).filter((diagnostic) => diagnostic.severity === "warning");
    const operationLabel = item.operation_label ? `${escapeHtml(item.operation_label)} · ` : "";
    return `<details class="strapi-product-result"><summary><span><b>${escapeHtml(item.program)}</b><small>${operationLabel}Fila ${escapeHtml(item.row_number)} · ${escapeHtml(item.status)} · ${escapeHtml(verificationLabel)}</small></span><span>${escapeHtml(item.changes?.length || 0)} cambios</span></summary><p>${escapeHtml(item.message || "")}</p>${sourceList ? `<small><b>Fuentes:</b> ${escapeHtml(sourceList)}</small>` : ""}${preserved}${warnings.length ? `<div class="strapi-inline-warning"><b>Advertencias:</b> ${escapeHtml(warnings.map((warning) => warning.message).join(" · "))}</div>` : ""}${changes ? `<div class="strapi-change-list">${changes}</div>` : "<small>Sin diferencias detectadas.</small>"}</details>`;
  }).join("") || "Sin resultados todavía.";
}

const FILE_COUNTRIES = {
  AR: "argentina", MX: "mexico", SV: "el-salvador", US: "usa", DO: "republica-dominicana",
  PA: "panama", BO: "bolivia", CL: "chile", CO: "colombia", EC: "ecuador", PE: "peru", PY: "paraguay",
};

export function initializeStrapiProductsModule({ api, showToast }) {
  const country = document.querySelector("#strapi-products-country");
  const productScope = document.querySelector("#strapi-products-scope");
  const scopeCount = document.querySelector("#strapi-products-scope-count");
  const scopeCountRow = document.querySelector("#strapi-products-scope-count-row");
  const file = document.querySelector("#strapi-products-file");
  const fullRun = document.querySelector("#strapi-products-full-run");
  const status = document.querySelector("#strapi-products-status");
  const dryRun = document.querySelector("#strapi-products-dry-run");
  const fichasFile = document.querySelector("#strapi-products-fichas-file");
  const reportDownload = document.querySelector("#strapi-products-report-download");
  const retryFailedButton = document.querySelector("#strapi-products-retry-failed");
  const clearButton = document.querySelector("#strapi-products-clear");
  if (!country || !file || !fullRun) return;

  const controls = [fullRun, clearButton, retryFailedButton].filter(Boolean);
  let lastCompletedJob = null;
  const selectedScope = () => productScope?.value === "all" ? "all" : String(Number(scopeCount?.value || 2));
  productScope?.addEventListener("change", () => {
    const limited = productScope.value !== "all";
    if (scopeCountRow) scopeCountRow.hidden = !limited;
    if (scopeCount) scopeCount.disabled = !limited;
  });

  api.strapiProductCountries().then((payload) => {
    country.innerHTML = '<option value="">Selecciona un país</option>';
    Object.entries(payload.countries || {}).forEach(([value, item]) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = item.label;
      country.append(option);
    });
  }).catch((error) => { status.textContent = error.message; });

  file.addEventListener("change", () => {
    const match = file.files[0]?.name.match(/^\s*(?:\[([A-Za-z]{2})\]|([A-Za-z]{2})(?=[-_ ]))/);
    const code = match ? (match[1] || match[2]).toUpperCase() : null;
    const countryValue = code ? FILE_COUNTRIES[code] : null;
    if (countryValue) {
      country.value = countryValue;
      status.textContent = `País detectado desde el archivo: ${country.options[country.selectedIndex]?.textContent || countryValue}.`;
    } else {
      status.textContent = "El archivo debe comenzar con un código como [AR] o MX-.";
    }
  });

  async function waitForJob(job) {
    let current;
    do {
      await new Promise((resolve) => setTimeout(resolve, 500));
      current = await api.strapiProductStatus(job.job_id);
      if (current.progress_message) status.textContent = current.progress_message;
    } while (current.status === "RUNNING");
    return current;
  }

  function exposeReport(link, job) {
    if (!link) return;
    link.hidden = !job?.download_url;
    if (job?.download_url) link.href = `${api.baseUrl}${job.download_url}`;
  }

  function exposeRetry(job) {
    if (!retryFailedButton) return;
    const failedStatuses = new Set(["FAILED", "NOT_FOUND", "AMBIGUOUS", "INVALID_DATA"]);
    const failed = (job?.results || []).filter((item) => failedStatuses.has(item.status) || item.verification?.ok === false);
    retryFailedButton.hidden = !job?.job_id || failed.length === 0;
    retryFailedButton.textContent = failed.length ? `Reintentar ${failed.length} fallido${failed.length === 1 ? "" : "s"}` : "Reintentar fallidos";
  }

  function clearForm() {
    file.value = "";
    if (fichasFile) fichasFile.value = "";
    country.value = "";
    if (productScope) productScope.value = "limit";
    if (scopeCount) {
      scopeCount.value = "2";
      scopeCount.disabled = false;
    }
    if (scopeCountRow) scopeCountRow.hidden = false;
    if (dryRun) dryRun.checked = true;
    status.textContent = "Selecciona país y Excel para comenzar.";
    const errorsBox = document.querySelector("#strapi-products-errors");
    if (errorsBox) {
      errorsBox.hidden = true;
      errorsBox.innerHTML = "";
    }
    document.querySelector("#strapi-products-summary").innerHTML = "";
    document.querySelector("#strapi-products-results").textContent = "Sin resultados todavía.";
    if (reportDownload) {
      reportDownload.hidden = true;
      reportDownload.removeAttribute("href");
    }
    if (retryFailedButton) retryFailedButton.hidden = true;
    lastCompletedJob = null;
  }

  async function startProcess(steps) {
    if (!file.files[0]) {
      showToast("Selecciona un archivo Excel.", "error");
      return;
    }
    const scope = selectedScope();
    if (scope !== "all" && (!Number.isInteger(Number(scope)) || Number(scope) < 1 || Number(scope) > 100000)) {
      showToast("Escribe una cantidad entre 1 y 100000.", "error");
      scopeCount?.focus();
      return;
    }
    const scopeLabel = scope === "all" ? "todos los productos" : `los primeros ${scope} productos`;
    const stepNames = { descriptions: "sincronizar contenido PDP" };
    const flowLabel = steps.map((step) => stepNames[step]).join(" y ");
    if (!dryRun.checked && !window.confirm(`La ejecución real aplicará ${flowLabel} en Strapi para ${scopeLabel}. ¿Deseas continuar?`)) return;

    controls.forEach((control) => { control.disabled = true; });
    const errorsBox = document.querySelector("#strapi-products-errors");
    if (errorsBox) {
      errorsBox.hidden = true;
      errorsBox.innerHTML = "";
    }
    if (reportDownload) {
      reportDownload.hidden = true;
      reportDownload.removeAttribute("href");
    }
    if (retryFailedButton) retryFailedButton.hidden = true;
    const completedJobs = [];
    try {
      for (const [index, step] of steps.entries()) {
        status.textContent = `${dryRun.checked ? "DRY RUN" : "Ejecución real"} · paso ${index + 1}/${steps.length}: ${stepNames[step]}...`;
        const started = step === "canonical"
          ? await api.runStrapiProducts(file.files[0], country.value, scope, dryRun.checked)
          : await api.runStrapiDescriptions(file.files[0], fichasFile?.files[0] || null, scope, dryRun.checked);
        const current = await waitForJob(started);
        current.operation_label = step === "canonical" ? "Canonical" : "PDP";
        completedJobs.push(current);
        lastCompletedJob = current;
        renderResults(current);
        exposeRetry(current);
        if (current.status === "FAILED") throw new Error(`${stepNames[step]}: ${current.message || "el proceso falló"}`);
      }

      const finalJob = completedJobs.at(-1);
      if (completedJobs.length === 1) {
        exposeReport(reportDownload, finalJob);
      } else if (completedJobs.length > 1) {
        const pdpJob = completedJobs.find((job) => job.operation_label === "PDP");
        const canonicalJob = completedJobs.find((job) => job.operation_label === "Canonical");
        if (canonicalJob && pdpJob) {
          const report = await api.createStrapiCombinedReport(canonicalJob.job_id, pdpJob.job_id);
          exposeReport(reportDownload, report);
        }
      }
      const inputTotal = finalJob.input_total ?? finalJob.summary?.total ?? 0;
      const selectedTotal = finalJob.selected_total ?? finalJob.summary?.total ?? 0;
      const finalStatus = completedJobs.some((job) => job.status === "WARNING") ? "WARNING" : "SUCCESS";
      const pdpJob = completedJobs.find((job) => job.operation_label === "PDP");
      status.textContent = `${finalStatus}: ${selectedTotal} de ${inputTotal} productos procesados${pdpJob ? ` · esquema integrado (${pdpJob.schema_version || "sin versión"})` : ""}.`;
      showToast("Proceso de Strapi terminado.", "info");
    } catch (error) {
      status.textContent = humanizeProcessError(error.message);
      const errorsBox = document.querySelector("#strapi-products-errors");
      if (errorsBox) {
        errorsBox.hidden = false;
        errorsBox.innerHTML = `<strong>No se pudo completar el proceso</strong><p>${escapeHtml(humanizeProcessError(error.message))}</p>`;
      }
      showToast(humanizeProcessError(error.message), "error");
    } finally {
      controls.forEach((control) => { control.disabled = false; });
    }
  }

  async function retryFailedProducts() {
    if (!lastCompletedJob?.job_id || !retryFailedButton) return;
    controls.forEach((control) => { control.disabled = true; });
    status.textContent = "Preparando reintento de productos fallidos...";
    try {
      const started = await api.retryStrapiProductJob(lastCompletedJob.job_id);
      const current = await waitForJob(started);
      lastCompletedJob = current;
      renderResults(current);
      exposeReport(reportDownload, current);
      exposeRetry(current);
      status.textContent = current.status === "FAILED"
        ? `El reintento terminó con errores generales: ${current.message || "revisa los diagnósticos."}`
        : `Reintento terminado: ${current.selected_total ?? current.summary?.total ?? 0} productos procesados.`;
      showToast("Reintento de productos terminado.", current.status === "FAILED" ? "error" : "info");
    } catch (error) {
      const message = humanizeProcessError(error.message);
      status.textContent = message;
      showToast(message, "error");
    } finally {
      controls.forEach((control) => { control.disabled = false; });
    }
  }

  fullRun.addEventListener("click", () => startProcess(["descriptions"]));
  clearButton?.addEventListener("click", clearForm);
  retryFailedButton?.addEventListener("click", retryFailedProducts);
}
