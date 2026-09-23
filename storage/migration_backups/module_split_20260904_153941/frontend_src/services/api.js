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
  runUtelBatch: (file, config, mapping) => {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("config", JSON.stringify(config));
    formData.append("mapping", JSON.stringify(mapping));
    return request("/api/bots/utel-inconcert/batch-run", { method: "POST", body: formData });
  },
  utelBatchStatus: (jobId) => request(`/api/bots/utel-inconcert/batch/${jobId}`),
  cancelUtelBatch: (jobId) => request(`/api/bots/utel-inconcert/batch/${jobId}/cancel`, { method: "POST" }),
  startBotRecorder: (config) => request("/api/bots/recorder/start", { method: "POST", body: JSON.stringify(config) }),
  botRecorderEvents: (sessionId) => request(`/api/bots/recorder/${sessionId}/events`),
  stopBotRecorder: (sessionId) => request(`/api/bots/recorder/${sessionId}/stop`, { method: "POST" }),
  runWeeklyAuto: (config) => request("/api/weekly-auto/run", { method: "POST", body: JSON.stringify(config) }),
  weeklyAutoStatus: (jobId) => request(`/api/weekly-auto/runs/${jobId}`),
  cancelWeeklyAuto: (jobId) => request(`/api/weekly-auto/runs/${jobId}/cancel`, { method: "POST" }),
  aiProviders: () => request("/api/ai/providers"),
  aiGenerate: (payload) => request("/api/ai/generate", { method: "POST", body: JSON.stringify(payload) }),
  validatePdp: (excelFile, docxFile) => {
    const formData = new FormData();
    formData.append("excel_file", excelFile);
    formData.append("docx_file", docxFile);
    return request("/api/pdp/validate", { method: "POST", body: formData });
  },
  validatePdpSemantic: (sourceFile, url, useAi = true) => {
    const formData = new FormData();
    formData.append("source_file", sourceFile);
    formData.append("url", url);
    formData.append("use_ai", String(useAi));
    return request("/api/pdp/semantic-validate", { method: "POST", body: formData });
  },
};
