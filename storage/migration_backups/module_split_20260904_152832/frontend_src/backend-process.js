"use strict";

// Utilidades de ciclo de vida del backend FastAPI invocadas por Electron.
const fs = require("node:fs");
const net = require("node:net");
const path = require("node:path");
const { randomUUID } = require("node:crypto");
const { spawn } = require("node:child_process");

function availablePort(preferred = 0) {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once("error", (error) => {
      if (error.code === "EADDRINUSE" && preferred !== 0) availablePort().then(resolve, reject);
      else reject(error);
    });
    server.listen(preferred, "127.0.0.1", () => {
      const port = server.address().port;
      server.close((error) => error ? reject(error) : resolve(port));
    });
  });
}

async function waitForBackend(child, apiUrl, instanceId, timeoutMs = 30000) {
  let failure;
  const onError = (error) => { failure = error; };
  const onExit = (code) => { failure = new Error(`El backend terminó durante el arranque (código ${code}).`); };
  child.on("error", onError);
  child.on("exit", onExit);
  try {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      if (failure) throw failure;
      if (child.exitCode !== null || child.signalCode) throw new Error("El backend no está ejecutándose.");
      try {
        const response = await fetch(`${apiUrl}/api/runtime`, { signal: AbortSignal.timeout(1000) });
        if (response.ok) {
          const runtime = await response.json();
          if (runtime.instance_id === instanceId && !failure && child.exitCode === null) return;
        }
      } catch { /* Puede seguir inicializando Python y la base de datos. */ }
      await new Promise((resolve) => setTimeout(resolve, 150));
    }
    throw new Error("El backend nuevo no respondió a tiempo. No se conectará a un proceso antiguo.");
  } finally {
    child.removeListener("error", onError);
    child.removeListener("exit", onExit);
  }
}

function stopBackend(child) {
  if (!child || !Number.isInteger(child.pid) || child.exitCode !== null || child.signalCode) return Promise.resolve();
  // En Windows el ejecutable de .venv puede crear otro python.exe: cerrar
  // solo el padre deja el servidor huérfano. Solo cerramos nuestro árbol.
  if (process.platform === "win32") {
    return new Promise((resolve) => {
      const killer = spawn("taskkill", ["/PID", String(child.pid), "/T", "/F"], { windowsHide: true, stdio: "ignore" });
      killer.once("error", resolve);
      killer.once("exit", resolve);
    });
  }
  child.kill();
  return Promise.resolve();
}

async function launchBackend(projectDirectory, environment = process.env) {
  const preferred = Number(environment.API_PORT || 8000);
  if (!Number.isInteger(preferred) || preferred < 0 || preferred > 65535) throw new Error("API_PORT no es un puerto válido.");
  const port = await availablePort(preferred);
  const instanceId = randomUUID();
  const apiUrl = `http://127.0.0.1:${port}`;
  const venvPython = path.join(projectDirectory, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
  const python = environment.PYTHON_COMMAND || (fs.existsSync(venvPython) ? venvPython : process.platform === "win32" ? "python" : "python3");
  const child = spawn(python, ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", String(port)], {
    cwd: path.join(projectDirectory, "backend"),
    env: { ...environment, PYTHONUNBUFFERED: "1", API_PORT: String(port), API_URL: apiUrl, QA_BACKEND_INSTANCE: instanceId },
    stdio: ["ignore", "pipe", "pipe"], windowsHide: true,
  });
  child.stdout.on("data", (data) => console.log(`[FastAPI] ${data}`));
  child.stderr.on("data", (data) => console.error(`[FastAPI] ${data}`));
  child.on("error", (error) => console.error("Error al iniciar FastAPI:", error.message));
  try {
    await waitForBackend(child, apiUrl, instanceId);
    return { child, apiUrl };
  } catch (error) {
    await stopBackend(child);
    throw error;
  }
}

module.exports = { availablePort, waitForBackend, launchBackend, stopBackend };
