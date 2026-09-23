"use strict";

import { api } from "../../../services/api.js";

export const weeklyAutoApi = {
  runWeeklyAuto: api.runWeeklyAuto,
  weeklyAutoStatus: api.weeklyAutoStatus,
  cancelWeeklyAuto: api.cancelWeeklyAuto,
};
