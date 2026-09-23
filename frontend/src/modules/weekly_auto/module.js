"use strict";

import { initializeWeeklyPhotosModule } from "./weekly_photos/module.js";
import { initializeWeeklyFormsModule } from "./weekly_forms/module.js";
import { initializeWeeklyPerformanceModule } from "./weekly_performance/module.js";
import { initializeWeeklyLeadsModule } from "./weekly_leads/module.js";

export function initializeWeeklyAutoModule(dependencies) {
  initializeWeeklyPhotosModule(dependencies);
  initializeWeeklyFormsModule(dependencies);
  initializeWeeklyPerformanceModule(dependencies);
  initializeWeeklyLeadsModule(dependencies);
}
