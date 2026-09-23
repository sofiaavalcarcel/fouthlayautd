"use strict";

const WEB_BASE_URL = ["http:", "https:"].includes(window.location.protocol)
  ? window.location.origin
  : "";
const API_BASE_URL =
  window.desktop?.apiUrl ||
  WEB_BASE_URL ||
  "http://127.0.0.1:8000";

async function request(path, options = {}) {
  const isFormData = options.body instanceof FormData;
  let response;

  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...options,
      headers: {
        ...(isFormData ? {} : { "Content-Type": "application/json" }),
        ...(options.headers || {}),
      },
    });
  } catch {
    throw new Error(
      `No se pudo conectar con el backend de Leads Deploy en ${API_BASE_URL}.`
    );
  }

  let payload = null;
  try {
    payload = await response.json();
  } catch {
    // Algunas descargas no devuelven JSON.
  }

  if (!response.ok) {
    const error = new Error(
      payload?.detail || `La API de Leads Deploy respondió con ${response.status}.`
    );
    error.status = response.status;
    throw error;
  }

  return payload;
}

export const leadsDeployApi = {
  baseUrl: API_BASE_URL,

  runUtelInconcertBot: (config) =>
    request("/api/bots/leads-deploy/run", {
      method: "POST",
      body: JSON.stringify(config),
    }),

  utelInconcertStatus: (jobId) =>
    request(`/api/bots/leads-deploy/runs/${jobId}`),

  cancelUtelInconcert: (jobId) =>
    request(`/api/bots/leads-deploy/runs/${jobId}/cancel`, {
      method: "POST",
    }),

  previewBotSpreadsheet: (file) => {
    const formData = new FormData();
    formData.append("file", file);
    return request("/api/bots/leads-deploy/spreadsheet-preview", {
      method: "POST",
      body: formData,
    });
  },

  runUtelBatch: (file, config, mapping) => {
    const formData = new FormData();
    formData.append("file", file);
    formData.append(
      "config",
      JSON.stringify({
        ...config,
        automation_module: "leads_deploy",
        workflow_mode: "form_validation",
      })
    );
    formData.append("mapping", JSON.stringify(mapping));
    return request("/api/bots/leads-deploy/batch-run", {
      method: "POST",
      body: formData,
    });
  },

  utelBatchStatus: (jobId) =>
    request(`/api/bots/leads-deploy/batch/${jobId}`),

  cancelUtelBatch: (jobId) =>
    request(`/api/bots/leads-deploy/batch/${jobId}/cancel`, {
      method: "POST",
    }),
};
