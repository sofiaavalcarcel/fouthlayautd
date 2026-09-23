"use strict";
const { spawnSync } = require('node:child_process');
const path = require('node:path');
module.exports = function ensureSetup(mode = 'web') {
  if (process.platform !== 'win32') {
    console.warn('Preparacion automatica disponible en Windows; en este sistema instale los requisitos de docs/instalacion.md.');
    return;
  }
  const result = spawnSync('powershell.exe', ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', path.join(__dirname, 'setup-windows.ps1'), '-Mode', mode], { stdio: 'inherit' });
  if (result.error || result.status !== 0) process.exit(result.status || 1);
};
