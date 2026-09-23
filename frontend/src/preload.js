"use strict";

// Puente mínimo y seguro entre Electron y el renderer; no expone Node.js.
const { contextBridge } = require("electron");

// Solo exponemos datos no sensibles. El renderer no recibe acceso a Node ni a secretos.
contextBridge.exposeInMainWorld("desktop", {
  platform: process.platform,
  apiUrl: process.env.API_URL || "http://127.0.0.1:8000",
});
