"use strict";

// Comparte la carga de Three.js entre las escenas del dashboard y evita dos
// descargas o inicializaciones paralelas cuando la página monta sus módulos.
const THREE_MODULE_URL = "https://cdn.jsdelivr.net/npm/three@0.180.0/build/three.module.js";
let threePromise = null;

export function loadThree() {
  if (!threePromise) {
    threePromise = import(THREE_MODULE_URL).catch((error) => {
      threePromise = null;
      throw error;
    });
  }
  return threePromise;
}
