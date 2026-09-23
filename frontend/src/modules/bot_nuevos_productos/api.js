"use strict";

import { api } from "../../services/api.js";

export const newProductsApi = {
  runUtelInconcertBot: api.runUtelInconcertBot,
  utelInconcertStatus: api.utelInconcertStatus,
  cancelUtelInconcert: api.cancelUtelInconcert,
  previewBotSpreadsheet: api.previewBotSpreadsheet,
  runUtelBatch: api.runUtelBatch,
  utelBatchStatus: api.utelBatchStatus,
  cancelUtelBatch: api.cancelUtelBatch,
};
