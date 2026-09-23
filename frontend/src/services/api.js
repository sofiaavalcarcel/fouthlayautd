"use strict";

// Cliente HTTP único: las pantallas consumen estas funciones, no `fetch` directamente.
const WEB_BASE_URL = ["http:", "https:"].includes(window.location.protocol) ? window.location.origin : "";
const API_BASE_URL = window.desktop?.apiUrl || WEB_BASE_URL || "http://127.0.0.1:8000";

// Normaliza las peticiones, cuerpos JSON/FormData y errores devueltos por FastAPI.
async function request(path, options = {}) {
  const isFormData = options.body instanceof FormData;
  let response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...options,
      headers: { ...(isFormData ? {} : { "Content-Type": "application/json" }), ...(options.headers || {}) },
    });
  } catch (error) {
    throw new Error(`No se pudo conectar con el servidor de automatizaciones en ${API_BASE_URL}. Verifica que el backend esté ejecutándose.`);
  }
  let payload;

  try {
    payload = await response.json();
  } catch {
    payload = null;
  }

  if (!response.ok) {
    const error = new Error(payload?.detail || `La API respondió con ${response.status}.`);
    error.status = response.status;
    throw error;
  }

  return payload;
}

// API de alto nivel organizada por dominio funcional.
export const api = {
  baseUrl: API_BASE_URL,
  health: () => request("/api/health"),
  dashboardSummary: () => request("/api/dashboard/summary"),
  executions: (limit = 20) => request(`/api/executions?limit=${limit}`),
  runBot: (config) => request("/api/bots/run", { method: "POST", body: JSON.stringify(config) }),
  botRunStatus: (jobId) => request(`/api/bots/runs/${jobId}`),
  runUtelInconcertBot: (config) => request("/api/bots/utel-inconcert/run", { method: "POST", body: JSON.stringify(config) }),
  utelInconcertStatus: (jobId) => request(`/api/bots/utel-inconcert/runs/${jobId}`),
  cancelUtelInconcert: (jobId) => request(`/api/bots/utel-inconcert/runs/${jobId}/cancel`, { method: "POST" }),
  previewBotSpreadsheet: (file) => {
    const formData = new FormData();
    formData.append("file", file);
    return request("/api/bots/utel-inconcert/spreadsheet-preview", { method: "POST", body: formData });
  },
  previewWeeklyFormsSpreadsheet: (file) => {
    const formData = new FormData();
    formData.append("file", file);
    return request("/api/weekly-auto/forms/spreadsheet-preview", { method: "POST", body: formData });
  },
  previewWeeklyLeadsSpreadsheet: (file) => {
    const formData = new FormData();
    formData.append("file", file);
    return request("/api/weekly-auto/leads/spreadsheet-preview", { method: "POST", body: formData });
  },
  previewFormValidationUrls: (urls, country = "") => request("/api/form-validation/urls/preview", {
    method: "POST",
    body: JSON.stringify({ urls, country }),
  }),
  runUtelBatch: (file, config, mapping) => {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("config", JSON.stringify(config));
    formData.append("mapping", JSON.stringify(mapping));
    return request("/api/bots/utel-inconcert/batch-run", { method: "POST", body: formData });
  },
  runWeeklyLeadsBatch: (file, config, mapping) => {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("config", JSON.stringify({ ...config, automation_module: "weekly_leads" }));
    formData.append("mapping", JSON.stringify(mapping));
    return request("/api/weekly-auto/leads/run", { method: "POST", body: formData });
  },
  runFormValidationUrls: (urls, config, country = "") => request("/api/form-validation/urls/run", {
    method: "POST",
    body: JSON.stringify({ urls, country, config }),
  }),
  utelBatchStatus: (jobId) => request(`/api/bots/utel-inconcert/batch/${jobId}`),
  weeklyLeadsStatus: (jobId) => request(`/api/bots/utel-inconcert/batch/${jobId}`),
  cancelUtelBatch: (jobId) => request(`/api/bots/utel-inconcert/batch/${jobId}/cancel`, { method: "POST" }),
  cancelWeeklyLeads: (jobId) => request(`/api/bots/utel-inconcert/batch/${jobId}/cancel`, { method: "POST" }),
  weeklyFormsDownloadUrl: (jobId) => `${API_BASE_URL}/api/bots/utel-inconcert/batch/${jobId}/download`,
  weeklyLeadsDownloadUrl: (jobId) => `${API_BASE_URL}/api/bots/utel-inconcert/batch/${jobId}/download`,
  runWeeklyPerformance: (file, sheetName = "Hoja 1", maxWorkers = 8) => {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("sheet_name", sheetName);
    formData.append("max_workers", String(maxWorkers));
    return request("/api/weekly-auto/performance/run", { method: "POST", body: formData });
  },
  weeklyPerformanceStatus: (jobId) => request(`/api/weekly-auto/performance/runs/${jobId}`),
  cancelWeeklyPerformance: (jobId) => request(`/api/weekly-auto/performance/runs/${jobId}/cancel`, { method: "POST" }),
  weeklyPerformanceDownloadUrl: (jobId) => `${API_BASE_URL}/api/weekly-auto/performance/runs/${jobId}/download`,
  startBotRecorder: (config) => request("/api/bots/recorder/start", { method: "POST", body: JSON.stringify(config) }),
  botRecorderEvents: (sessionId) => request(`/api/bots/recorder/${sessionId}/events`),
  stopBotRecorder: (sessionId) => request(`/api/bots/recorder/${sessionId}/stop`, { method: "POST" }),
  runWeeklyAuto: (config) => request("/api/weekly-auto/run", { method: "POST", body: JSON.stringify(config) }),
  weeklyAutoStatus: (jobId) => request(`/api/weekly-auto/runs/${jobId}`),
  cancelWeeklyAuto: (jobId) => request(`/api/weekly-auto/runs/${jobId}/cancel`, { method: "POST" }),
  strapiProductCountries: () => request("/api/strapi/products/countries"),
  runStrapiProducts: (file, country, productScope = "2", dryRun = true) => {
    const formData = new FormData();
    formData.append("file", file);
    if (country) formData.append("country", country);
    formData.append("product_scope", productScope);
    formData.append("dry_run", String(dryRun));
    return request("/api/strapi/products/run", { method: "POST", body: formData });
  },
  strapiProductStatus: (jobId) => request(`/api/strapi/products/jobs/${jobId}`),
  createStrapiCombinedReport: (canonicalJobId, pdpJobId) => {
    const formData = new FormData();
    formData.append("canonical_job_id", canonicalJobId);
    formData.append("pdp_job_id", pdpJobId);
    return request("/api/strapi/products/combined-report", { method: "POST", body: formData });
  },
  runStrapiDescriptions: (file, fichasFile, productScope = "2", dryRun = true) => {
    const formData = new FormData();
    formData.append("file", file);
    if (fichasFile) formData.append("fichas_file", fichasFile);
    formData.append("product_scope", productScope);
    formData.append("dry_run", String(dryRun));
    return request("/api/strapi/products/descriptions/run", { method: "POST", body: formData });
  },
  aiProviders: () => request("/api/ai/providers"),
  aiGenerate: (payload) => request("/api/ai/generate", { method: "POST", body: JSON.stringify(payload) }),
};
