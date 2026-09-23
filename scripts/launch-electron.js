"use strict";

// Punto de arranque de escritorio: delega en Electron el proceso principal del frontend.
const { spawn } = require("node:child_process");
const path = require("node:path");
require('./ensure-setup')('desktop');

// Algunos entornos de desarrollo exportan esta variable y hacen que Electron
// se ejecute como Node.js. El launcher la elimina antes de iniciar la ventana.
const { ELECTRON_RUN_AS_NODE, ...cleanEnvironment } = process.env;
const electronCli = path.join(__dirname, "..", "node_modules", "electron", "cli.js");
const child = spawn(process.execPath, [electronCli, "."], {
  cwd: path.resolve(__dirname, ".."),
  env: cleanEnvironment,
  stdio: "inherit",
  windowsHide: false,
});

child.on("exit", (code, signal) => {
  if (signal) process.kill(process.pid, signal);
  process.exit(code ?? 1);
});
