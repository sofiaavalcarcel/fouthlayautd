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
  if (errorsBox) {
    errorsBox.hidden = errors.length === 0;
    errorsBox.innerHTML = errors.length
      ? `<strong>Errores encontrados</strong><ul>${errors.map((item) => `<li><b>${escapeHtml(item.program || "Producto sin nombre")}</b>: ${escapeHtml(item.message || "No se pudo completar este producto.")}</li>`).join("")}</ul>`
      : "";
  }
  const summary = { ...(job.summary || {}) };
  if (results.some((item) => item.verification)) {
    summary.productos_verificados = results.filter((item) => item.verification?.ok === true).length;
    summary.fallos_verificacion = results.filter((item) => item.verification?.ok === false).length;
    summary.cambios_propuestos_o_aplicados = results.reduce((total, item) => total + (item.changes?.length || 0), 0);
  }
  const summaryLabels = { total: "Productos", updated: "Actualizados", dry_run: "Dry run", skipped: "Sin cambios", not_found: "No encontrados", ambiguous: "Ambiguos", invalid_data: "Datos inválidos", failed: "Fallidos", productos_verificados: "Verificados", fallos_verificacion: "Fallos de verificación", cambios_propuestos_o_aplicados: "Cambios", pdp_procesados: "PDP procesados" };
  document.querySelector("#strapi-products-summary").innerHTML = Object.entries(summary).map(([key, value]) => `<div class="pdp-summary-card"><strong>${escapeHtml(value)}</strong><span>${escapeHtml(summaryLabels[key] || key)}</span></div>`).join("");
  document.querySelector("#strapi-products-results").innerHTML = results.map((item) => {
    const verification = item.verification || {};
    const verificationLabel = item.status === "DRY_RUN" ? "Dry run · sin escritura" : verification.ok === true ? "Verificado" : verification.ok === false ? "Falló verificación" : "No verificado";
    const changes = (item.changes || []).map((change) => `<div class="strapi-change-row"><strong>${escapeHtml(change.field)}</strong><span>${escapeHtml(change.action || "update")} · ${change.verified === true ? "verificado" : change.verified === false ? "no coincide" : "sin verificación"}</span><small>Antes: ${escapeHtml(JSON.stringify(change.before ?? null))}</small><small>Después: ${escapeHtml(JSON.stringify(change.after ?? null))}</small>${change.created_id != null ? `<small>ID creado: ${escapeHtml(change.created_id)}</small>` : ""}</div>`).join("");
    const operationLabel = item.operation_label ? `${escapeHtml(item.operation_label)} · ` : "";
    return `<details class="strapi-product-result"><summary><span><b>${escapeHtml(item.program)}</b><small>${operationLabel}Fila ${escapeHtml(item.row_number)} · ${escapeHtml(item.status)} · ${escapeHtml(verificationLabel)}</small></span><span>${escapeHtml(item.changes?.length || 0)} cambios</span></summary><p>${escapeHtml(item.message || "")}</p>${changes ? `<div class="strapi-change-list">${changes}</div>` : "<small>Sin diferencias detectadas.</small>"}</details>`;
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
  const clearButton = document.querySelector("#strapi-products-clear");
  if (!country || !file || !fullRun) return;

  const controls = [fullRun, clearButton].filter(Boolean);
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
    const match = file.files[0]?.name.match(/^\s*\[([A-Za-z]{2})\]/);
    const countryValue = match ? FILE_COUNTRIES[match[1].toUpperCase()] : null;
    if (countryValue) {
      country.value = countryValue;
      status.textContent = `País detectado desde el archivo: ${country.options[country.selectedIndex]?.textContent || countryValue}.`;
    } else {
      status.textContent = "El archivo debe comenzar con un código como [AR].";
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
        renderResults(current);
        if (current.blocking_reason) throw new Error(current.blocking_reason);
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

  fullRun.addEventListener("click", () => startProcess(["descriptions"]));
  clearButton?.addEventListener("click", clearForm);
}
