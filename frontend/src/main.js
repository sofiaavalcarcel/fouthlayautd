"use strict";

// Proceso principal de Electron: crea la ventana y coordina el backend local.
const { app, BrowserWindow, dialog } = require("electron");
const path = require("node:path");
const { launchBackend, stopBackend } = require("./backend-process");

// Estado del proceso FastAPI iniciado para la aplicación de escritorio.
let backendProcess;

async function startBackend() {
  const launched = await launchBackend(path.resolve(__dirname, "../.."));
  backendProcess = launched.child;
  process.env.API_URL = launched.apiUrl;
  backendProcess.on("exit", (code) => {
    if (!app.isQuitting) {
      dialog.showErrorBox("Backend desconectado", `El motor de pruebas terminó (código ${code}). Reinicia la aplicación antes de ejecutar otra prueba.`);
    }
  });
}

function createWindow() {
  const window = new BrowserWindow({
    width: 1440,
    height: 920,
    minWidth: 1100,
    minHeight: 720,
    backgroundColor: "#0b1220",
    title: "QA Automation",
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      preload: path.join(__dirname, "preload.js"),
    },
  });

  window.webContents.on("console-message", (_event, level, message, line, sourceId) => {
    if (level >= 2) console.error(`[Renderer] ${message} (${sourceId}:${line})`);
  });
  window.webContents.on("render-process-gone", (_event, details) => {
    console.error(`[Renderer] proceso terminado: ${details.reason}`);
  });
  window.loadFile(path.resolve(__dirname, "../index.html"));
}

app.whenReady().then(async () => {
  try {
    await startBackend();
    createWindow();
  } catch (error) {
    dialog.showErrorBox("No se pudo iniciar el motor de pruebas", error.message);
    app.quit();
    return;
  }

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("before-quit", (event) => {
  if (app.isQuitting) return;
  app.isQuitting = true;
  event.preventDefault();
  stopBackend(backendProcess).finally(() => app.quit());
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
