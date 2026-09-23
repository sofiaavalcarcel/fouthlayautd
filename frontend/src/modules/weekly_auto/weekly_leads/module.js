"use strict";

import { initializeLeadSubmissionModule } from "../lead_submission/module.js";

// Módulo independiente para matrices de envíos generales de leads.
export function initializeWeeklyLeadsModule(dependencies) {
  initializeLeadSubmissionModule(dependencies, {
    key: "weekly-leads",
    title: "Form Validation",
    fileLabel: "Excel de Form Validation (.xlsx)",
    description: "Envía y valida leads desde QA.xlsx o reportes de landings (Country/pais, Nivel, URL y Lead).",
    readyMessage: "Selecciona la matriz de leads.",
    runLabel: "Ejecutar Form Validation",
    automationModule: "weekly_leads",
    preview: dependencies.previewWeeklyLeadsSpreadsheet,
    runBatch: dependencies.runWeeklyLeadsBatch,
    status: dependencies.weeklyLeadsStatus,
    cancel: dependencies.cancelWeeklyLeads,
    downloadUrl: dependencies.weeklyLeadsDownloadUrl,
    viewId: "view-weekly-leads",
    allowManualUrls: true,
    previewManualUrls: dependencies.previewFormValidationUrls,
    runManualUrls: dependencies.runFormValidationUrls,
  });
}
