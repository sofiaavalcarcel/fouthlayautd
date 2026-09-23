"use strict";

import { initializeLeadSubmissionModule } from "../lead_submission/module.js";

// Conserva la entrada pública histórica de Weekly Forms y su contrato visual.
export function initializeWeeklyFormsModule(dependencies) {
  initializeLeadSubmissionModule(dependencies, {
    key: "weekly-forms",
    title: "Weekly Forms",
    fileLabel: "Excel de Weekly Forms (.xlsx)",
    description: "Lee Country, Nivel, Activo de Test, Location y Lead.",
    readyMessage: "Selecciona la matriz QA.",
    runLabel: "Ejecutar Weekly Forms",
    automationModule: "weekly_forms",
    viewId: "view-weekly-forms",
  });
}
