"use strict";

// Coordinador de la interfaz: navegación, dashboard e historial compartido.
import { api } from "../services/api.js?v=pdp-integrated-schema-1";
import { leadsDeployApi } from "../services/leads-deploy-api.js";
import { initializeBotModule } from "./bot-module.js?v=new-products-lead-destination-1";
import { initializeLeadsDeployModule } from "./leads-deploy-module.js?v=leads-deploy-isolated-4";
import { initializeWeeklyAutoModule } from "./weekly-auto-module.js";
import { initializeStrapiProductsModule } from "./strapi-products-module.js?v=pdp-integrated-schema-2-progress-errors";
import { initializeGooeyButtons } from "./gooey-buttons.js";
import { initializeOptionWheel } from "./option-wheel.js";
import { initializeLiquidButtons } from "./liquid-buttons.js";

// Estado mínimo persistido para restaurar la última pantalla abierta.
const LAST_VIEW_KEY = "qa-automation.last-view";
const WEEKLY_AUTO_EXPANDED_KEY = "qa-automation.weekly-auto-expanded";
const WEEKLY_AUTO_VIEWS = new Set(["weekly-photos", "weekly-forms", "weekly-performance"]);
const state = { activeView: "dashboard", weeklyAutoExpanded: false };
const runtimeMode = window.desktop ? "desktop" : "web";

const viewMeta = {
  dashboard: { title: "Dashboard", description: "Resumen operativo" },
  excel: { title: "Strapi productos", description: "Sincronización PDP" },
  bot: { title: "Bot de nuevos productos", description: "Automatizaciones" },
  "leads-deploy": { title: "Bot Leads Deploy", description: "Automatizaciones" },
  "weekly-auto": { title: "Weekly Auto", description: "Automatizaciones" },
  "weekly-photos": { title: "Weekly Photos", description: "Weekly Auto" },
  "weekly-forms": { title: "Weekly Forms", description: "Weekly Auto" },
  "weekly-performance": { title: "Weekly Performance", description: "Weekly Auto" },
  "weekly-leads": { title: "Form Validation", description: "Automatizaciones" },
  history: { title: "Historial", description: "Trazabilidad" },
  settings: { title: "Configuración", description: "Administración" },
};

// Referencias centralizadas al DOM para evitar selectores repetidos.
function selectElements() {
  return {
    title: document.querySelector("#page-title"),
    views: document.querySelectorAll("[data-view-panel]"),
    navigation: document.querySelectorAll("[data-view]"),
    refreshButton: document.querySelector("#refresh-button"),
    lastUpdated: document.querySelector("#last-updated"),
    toast: document.querySelector("#toast"),
    connectionDot: document.querySelector("#connection-dot"),
    connectionLabel: document.querySelector("#connection-label"),
    apiDot: document.querySelector("#api-dot"),
    apiStatus: document.querySelector("#api-status"),
    healthPulse: document.querySelector("#health-pulse"),
    runtimeLabel: document.querySelector("#runtime-label"),
    userAvatar: document.querySelector(".user-avatar"),
  };
}

const elements = selectElements();

function escapeHtml(value) {
  // Los datos del historial vienen de SQLite y se escapan antes de insertarlos en la tabla.
  return String(value ?? "—")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatDate(value) {
  if (!value) return "—";
  const parsedDate = new Date(value);
  if (Number.isNaN(parsedDate.getTime())) return value;
  return parsedDate.toLocaleString("es-CO", { dateStyle: "medium", timeStyle: "short" });
}

function formatDuration(seconds) {
  if (seconds === null || seconds === undefined) return "—";
  return `${Number(seconds).toFixed(1)} s`;
}

function statusClass(status) {
  return { SUCCESS: "success", FAIL: "error", WARNING: "warning", RUNNING: "running" }[status] || "pending";
}

function statusLabel(status) {
  return { SUCCESS: "PASS", FAIL: "FAIL", WARNING: "WARNING", RUNNING: "RUNNING" }[status] || "PENDING";
}

function executionRow(execution) {
  return `<tr>
    <td><strong>${escapeHtml(execution.name)}</strong></td>
    <td><span class="type-label">${escapeHtml(execution.automation_type)}</span></td>
    <td>${escapeHtml(formatDate(execution.started_at))}</td>
    <td>${escapeHtml(formatDuration(execution.duration_seconds))}</td>
    <td><span class="status-badge ${statusClass(execution.status)}">${statusLabel(execution.status)}</span></td>
  </tr>`;
}

// Renderizado de datos procedentes de la API; todo valor dinámico se escapa antes.
function renderHistory(executions) {
  const body = document.querySelector("#history-body");
  const fullBody = document.querySelector("#full-history-body");
  const emptyRow = '<tr><td colspan="5" class="table-empty">No hay ejecuciones registradas todavía.</td></tr>';
  const rows = executions.length ? executions.map(executionRow).join("") : emptyRow;
  if (body) body.innerHTML = rows;
  if (fullBody) fullBody.innerHTML = rows;
  const queued = executions.filter((execution) => execution.status === "PENDING").length;
  const running = executions.filter((execution) => execution.status === "RUNNING").length;
  const completed = executions.filter((execution) => ["SUCCESS", "FAIL", "WARNING"].includes(execution.status)).length;
  const updateStat = (selector, value) => {
    const element = document.querySelector(selector);
    if (element) element.textContent = value;
  };
  updateStat("#stat-queued", queued);
  updateStat("#stat-running", running);
  updateStat("#stat-completed", completed);
  const recent = document.querySelector("#recent-activity");
  if (recent) {
    recent.innerHTML = executions.slice(0, 4).map((execution) => `<div class="recent-item"><i class="health-dot ${statusClass(execution.status) === "success" ? "online" : "offline"}"></i><span><b>${escapeHtml(execution.name)}</b><small>${escapeHtml(execution.summary || statusLabel(execution.status))}</small></span><small>${escapeHtml(formatDate(execution.started_at))}</small></div>`).join("") || '<div class="recent-item recent-item-empty"><i class="health-dot online"></i><span><b>Sin actividad reciente</b><small>Los eventos aparecerán aquí.</small></span><small>Ahora</small></div>';
  }
}

function renderLatest(execution) {
  const status = document.querySelector("#latest-status");
  const content = document.querySelector("#latest-content");

  if (!execution) {
    status.className = "status-badge pending";
    status.textContent = "PENDIENTE";
    content.innerHTML = `<div class="empty-state compact"><div class="empty-icon">◌</div><strong>Aún no hay ejecuciones</strong><span>Las automatizaciones aparecerán aquí cuando se construyan en las siguientes fases.</span></div>`;
    return;
  }

  status.className = `status-badge ${statusClass(execution.status)}`;
  status.textContent = statusLabel(execution.status);
  content.innerHTML = `<div class="latest-execution"><div class="latest-icon">${execution.status === "SUCCESS" ? "✓" : "!"}</div><div><strong>${escapeHtml(execution.name)}</strong><span>${escapeHtml(execution.summary || "Sin resumen disponible")}</span><small>${escapeHtml(formatDate(execution.started_at))} · ${escapeHtml(formatDuration(execution.duration_seconds))}</small></div></div>`;
}

function renderSummary(summary) {
  document.querySelector("#metric-total").textContent = summary.total_today;
  document.querySelector("#metric-success").textContent = summary.successful_today;
  document.querySelector("#metric-failed").textContent = summary.failed_today;
  document.querySelector("#metric-changes").textContent = summary.changes_detected_today;
  const donutTotal = document.querySelector("#donut-total");
  const legendSuccess = document.querySelector("#legend-success");
  const legendFailed = document.querySelector("#legend-failed");
  const legendChanges = document.querySelector("#legend-changes");
  if (donutTotal) donutTotal.textContent = summary.total_today;
  if (legendSuccess) legendSuccess.textContent = summary.successful_today;
  if (legendFailed) legendFailed.textContent = summary.failed_today;
  if (legendChanges) legendChanges.textContent = summary.changes_detected_today;
  const total = Number(summary.total_today) || 0;
  const updateRate = (selector, value, suffix = "del total") => {
    const element = document.querySelector(selector);
    if (!element) return;
    const rate = total > 0 ? Math.round((Number(value) || 0) * 100 / total) : 0;
    element.textContent = `${rate}% ${suffix}`;
    element.closest(".metric-card")?.style.setProperty("--metric-activity", `${Math.max(8, rate)}%`);
  };
  const totalRate = document.querySelector("#metric-total-rate");
  if (totalRate) totalRate.textContent = `${total > 0 ? 100 : 0}% hoy`;
  updateRate("#metric-success-rate", summary.successful_today);
  updateRate("#metric-failed-rate", summary.failed_today);
  updateRate("#metric-changes-rate", summary.changes_detected_today);
  const donut = document.querySelector(".donut-chart");
  if (donut) {
    const successEnd = total > 0 ? (Number(summary.successful_today) || 0) * 100 / total : 0;
    const failedEnd = total > 0 ? successEnd + (Number(summary.failed_today) || 0) * 100 / total : 0;
    donut.style.setProperty("--success-end", `${successEnd}%`);
    donut.style.setProperty("--failed-end", `${failedEnd}%`);
    donut.classList.toggle("is-empty", total === 0);
  }
  renderLatest(summary.latest_execution);
}

function setConnectionStatus(online) {
  const { connectionDot: dot, connectionLabel: label, apiDot, apiStatus, healthPulse: pulse } = elements;
  dot.classList.toggle("offline", !online);
  apiDot.classList.toggle("online", online);
  apiDot.classList.toggle("offline", !online);
  pulse.classList.toggle("offline", !online);
  label.textContent = online ? "Backend conectado" : "Backend desconectado";
  apiStatus.textContent = online ? "Operativa" : "No disponible";
  apiStatus.classList.toggle("online-text", online);
}

function showToast(message, type = "info") {
  elements.toast.textContent = message;
  elements.toast.className = `toast visible ${type}`;
  window.setTimeout(() => elements.toast.classList.remove("visible"), 3500);
}

// Abre o cierra el grupo de módulos sin alterar los contratos de navegación.
function setWeeklyAutoExpanded(expanded) {
  const parent = document.querySelector("[data-weekly-parent='true']");
  const submenu = document.querySelector("#weekly-auto-subnav");
  if (!parent || !submenu) return;
  state.weeklyAutoExpanded = Boolean(expanded);
  parent.setAttribute("aria-expanded", String(state.weeklyAutoExpanded));
  submenu.hidden = !state.weeklyAutoExpanded;
  parent.classList.toggle("expanded", state.weeklyAutoExpanded);
  localStorage.setItem(WEEKLY_AUTO_EXPANDED_KEY, String(state.weeklyAutoExpanded));
}

async function refreshDashboard() {
  elements.refreshButton.classList.add("loading");
  try {
    const [health, summary, history] = await Promise.all([api.health(), api.dashboardSummary(), api.executions(20)]);
    renderSummary(summary);
    renderHistory(history.items);
    setConnectionStatus(health.status === "ok");
    elements.lastUpdated.textContent = `Actualizado ${new Date().toLocaleTimeString("es-CO", { hour: "2-digit", minute: "2-digit" })}`;
  } catch (error) {
    setConnectionStatus(false);
    showToast(`No se pudo actualizar el dashboard: ${error.message}`, "error");
  } finally {
    elements.refreshButton.classList.remove("loading");
  }
}

// Navegación interna SPA: activa un único panel y actualiza el encabezado.
function navigate(viewName) {
  if (!viewMeta[viewName]) return;
  state.activeView = viewName;
  localStorage.setItem(LAST_VIEW_KEY, viewName);
  if (WEEKLY_AUTO_VIEWS.has(viewName)) setWeeklyAutoExpanded(true);
  else if (viewName !== "weekly-auto") setWeeklyAutoExpanded(false);
  elements.navigation.forEach((item) => {
    const isWeeklyParent = item.dataset.view === "weekly-auto" && WEEKLY_AUTO_VIEWS.has(viewName);
    item.classList.toggle("active", item.dataset.view === viewName || isWeeklyParent);
  });
  elements.views.forEach((view) => view.classList.toggle("active", view.dataset.viewPanel === viewName));
  elements.title.textContent = viewMeta[viewName].title;
}

function bindEvents() {
  elements.navigation.forEach((item) => item.addEventListener("click", () => {
    if (item.dataset.weeklyParent === "true") {
      const willExpand = !state.weeklyAutoExpanded;
      setWeeklyAutoExpanded(willExpand);
      if (willExpand) navigate("weekly-auto");
      return;
    }
    navigate(item.dataset.view);
  }));
  elements.refreshButton.addEventListener("click", refreshDashboard);
  document.querySelector("#today-label").textContent = new Date().toLocaleDateString("es-CO", { day: "numeric", month: "long", year: "numeric" });
  document.querySelector("#api-url-label").textContent = api.baseUrl;
  document.documentElement.dataset.runtime = runtimeMode;
  if (elements.runtimeLabel) elements.runtimeLabel.textContent = runtimeMode === "desktop" ? "Aplicación desktop" : "Aplicación web";
  if (elements.userAvatar) elements.userAvatar.title = runtimeMode === "desktop" ? "Sesión local desktop" : "Sesión web local";
}

bindEvents();
initializeOptionWheel({
  navigation: document.querySelector(".navigation"),
  sourceItems: [...document.querySelectorAll(".navigation > .nav-item, .navigation > .nav-submenu > .nav-subitem")],
  options: { loop: true },
  // La rueda es una capa visual; la navegación real sigue pasando por los
  // botones originales y, por tanto, conserva sus rutas y estados actuales.
  onChange: (_index, source) => source?.click(),
});
initializeGooeyButtons();
// Descarta una vista guardada que ya no existe para evitar una pantalla vacía
// cuando se retiran módulos del menú en una actualización de la interfaz.
const persistedView = localStorage.getItem(LAST_VIEW_KEY);
const requestedView = new URLSearchParams(window.location.search).get("view");
state.activeView = viewMeta[requestedView]
  ? requestedView
  : persistedView && viewMeta[persistedView] ? persistedView : "dashboard";
if (state.activeView !== persistedView) localStorage.setItem(LAST_VIEW_KEY, state.activeView);
state.weeklyAutoExpanded = localStorage.getItem(WEEKLY_AUTO_EXPANDED_KEY) === "true" || WEEKLY_AUTO_VIEWS.has(state.activeView);
setWeeklyAutoExpanded(state.weeklyAutoExpanded);
navigate(state.activeView);
initializeBotModule({
  showToast,
  runUtelInconcertBot: api.runUtelInconcertBot,
  utelInconcertStatus: api.utelInconcertStatus,
  cancelUtelInconcert: api.cancelUtelInconcert,
  previewBotSpreadsheet: api.previewBotSpreadsheet,
  runUtelBatch: api.runUtelBatch,
  utelBatchStatus: api.utelBatchStatus,
  cancelUtelBatch: api.cancelUtelBatch,
});
initializeLeadsDeployModule({
  showToast,
  runUtelInconcertBot: leadsDeployApi.runUtelInconcertBot,
  utelInconcertStatus: leadsDeployApi.utelInconcertStatus,
  cancelUtelInconcert: leadsDeployApi.cancelUtelInconcert,
  previewBotSpreadsheet: leadsDeployApi.previewBotSpreadsheet,
  runUtelBatch: leadsDeployApi.runUtelBatch,
  utelBatchStatus: leadsDeployApi.utelBatchStatus,
  cancelUtelBatch: leadsDeployApi.cancelUtelBatch,
});
initializeWeeklyAutoModule({
  showToast,
  runWeeklyAuto: api.runWeeklyAuto,
  weeklyAutoStatus: api.weeklyAutoStatus,
  cancelWeeklyAuto: api.cancelWeeklyAuto,
  previewWeeklyFormsSpreadsheet: api.previewWeeklyFormsSpreadsheet,
  runWeeklyFormsBatch: api.runUtelBatch,
  weeklyFormsStatus: api.utelBatchStatus,
  cancelWeeklyForms: api.cancelUtelBatch,
  weeklyFormsDownloadUrl: api.weeklyFormsDownloadUrl,
  runWeeklyPerformance: api.runWeeklyPerformance,
  weeklyPerformanceStatus: api.weeklyPerformanceStatus,
  cancelWeeklyPerformance: api.cancelWeeklyPerformance,
  weeklyPerformanceDownloadUrl: api.weeklyPerformanceDownloadUrl,
  previewWeeklyLeadsSpreadsheet: api.previewWeeklyLeadsSpreadsheet,
  previewFormValidationUrls: api.previewFormValidationUrls,
  runWeeklyLeadsBatch: api.runWeeklyLeadsBatch,
  runFormValidationUrls: api.runFormValidationUrls,
  weeklyLeadsStatus: api.weeklyLeadsStatus,
  cancelWeeklyLeads: api.cancelWeeklyLeads,
  weeklyLeadsDownloadUrl: api.weeklyLeadsDownloadUrl,
});
initializeStrapiProductsModule({ api, showToast });
initializeLiquidButtons();
refreshDashboard();
window.setInterval(refreshDashboard, 30000);
