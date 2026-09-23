"use strict";

import { loadThree } from "./three-runtime.js?v=utel-scenes-1";

// Controlador visual del robot: mantiene la API pública existente mientras la
// representación pasa de una imagen 2D a una escena 3D independiente.
const STYLE_ID = "dashboard-robot-face-style";
const ROBOT_STATES = new Set(["idle", "working", "success", "error", "sleep"]);
let activeRobot = null;

const STATE_COLORS = {
  idle: { eye: 0x9fe770, emissive: 0x06b706, mouth: 0x06b706, chest: 0x4000bc },
  working: { eye: 0xffb937, emissive: 0xff9f1c, mouth: 0xffb937, chest: 0xffb937 },
  success: { eye: 0x9fe770, emissive: 0x06b706, mouth: 0x06b706, chest: 0x06b706 },
  error: { eye: 0xff7a7a, emissive: 0xd53333, mouth: 0xd53333, chest: 0xd53333 },
  sleep: { eye: 0x9ba89b, emissive: 0x3f5d3b, mouth: 0x657461, chest: 0x657461 },
};

function installStylesheet() {
  let link = document.getElementById(STYLE_ID);
  if (!link) {
    link = document.createElement("link");
    link.id = STYLE_ID;
    link.rel = "stylesheet";
    document.head.appendChild(link);
  }
  const href = new URL("./dashboard-robot.css?v=robot-3d-2", import.meta.url).href;
  if (link.href !== href) link.href = href;
}

function statusToState(value) {
  const status = String(value || "").trim().toUpperCase();
  if (status === "RUNNING") return "working";
  if (status === "PASS" || status === "SUCCESS") return "success";
  if (status === "FAIL" || status === "ERROR") return "error";
  if (status === "WARNING") return "working";
  return "idle";
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function createMouthGeometry(THREE, state) {
  const centerY = state === "success" ? -0.24 : state === "error" ? -0.08 : state === "working" ? -0.16 : -0.21;
  const curve = new THREE.QuadraticBezierCurve3(
    new THREE.Vector3(-0.22, -0.16, 0.755),
    new THREE.Vector3(0, centerY, 0.755),
    new THREE.Vector3(0.22, -0.16, 0.755),
  );
  return new THREE.BufferGeometry().setFromPoints(curve.getPoints(18));
}

// Construye la geometría, materiales, iluminación y animación del robot.
function createRobotScene(THREE, host, getState, reducedMotion) {
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(24, 1, 0.1, 100);
  camera.position.set(0, 0.06, 5.15);
  camera.lookAt(0, 0.04, 0);

  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "high-performance" });
  renderer.setClearColor(0x000000, 0);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  renderer.domElement.setAttribute("aria-hidden", "true");
  renderer.domElement.tabIndex = -1;
  host.replaceChildren(renderer.domElement);
  host.classList.add("utel-robot-3d");

  // Luces de marca: verde para volumen, morado para contraluz y amarillo como
  // brillo de estado en las piezas metálicas.
  scene.add(new THREE.AmbientLight(0xdff7cf, 1.65));
  const keyLight = new THREE.DirectionalLight(0x9fe770, 2.1);
  keyLight.position.set(2.8, 3.2, 4.2);
  scene.add(keyLight);
  const rimLight = new THREE.DirectionalLight(0x4000bc, 1.25);
  rimLight.position.set(-3.2, 0.8, 2.5);
  scene.add(rimLight);
  const accentLight = new THREE.PointLight(0xffb937, 1.1, 4.5);
  accentLight.position.set(0.2, -0.25, 2.2);
  scene.add(accentLight);

  const robotGroup = new THREE.Group();
  robotGroup.position.y = -0.05;
  scene.add(robotGroup);

  const bodyMaterial = new THREE.MeshStandardMaterial({ color: 0x9fe770, metalness: 0.28, roughness: 0.32 });
  const trimMaterial = new THREE.MeshStandardMaterial({ color: 0x06b706, metalness: 0.38, roughness: 0.24 });
  const visorMaterial = new THREE.MeshPhysicalMaterial({
    color: 0x122315,
    metalness: 0.42,
    roughness: 0.16,
    clearcoat: 0.9,
    clearcoatRoughness: 0.18,
  });
  const eyeMaterial = new THREE.MeshStandardMaterial({
    color: 0x9fe770,
    emissive: 0x06b706,
    emissiveIntensity: 2.8,
    metalness: 0.05,
    roughness: 0.16,
  });
  const pupilMaterial = new THREE.MeshStandardMaterial({ color: 0x1c2d1a, roughness: 0.16, metalness: 0.1 });
  const mouthMaterial = new THREE.LineBasicMaterial({ color: 0x06b706, transparent: true, opacity: 0.96 });
  const ringAccentMaterial = new THREE.MeshBasicMaterial({ color: 0x06b706, transparent: true, opacity: 0.42, blending: THREE.AdditiveBlending, depthWrite: false });
  const shadowMaterial = new THREE.MeshBasicMaterial({ color: 0x1c2d1a, transparent: true, opacity: 0.13, depthWrite: false });

  // El aro morado exterior se elimina para que el robot quede limpio junto al
  // planeta; se conserva únicamente el pequeño acento verde del visor/halo.
  const ringAccent = new THREE.Mesh(new THREE.TorusGeometry(0.86, 0.009, 10, 100), ringAccentMaterial);
  ringAccent.rotation.x = -0.36;
  ringAccent.rotation.y = 0.38;
  ringAccent.position.z = -0.3;
  robotGroup.add(ringAccent);

  const shadow = new THREE.Mesh(new THREE.CircleGeometry(0.82, 48), shadowMaterial);
  shadow.rotation.x = -Math.PI / 2;
  shadow.position.set(0, -0.84, 0.12);
  robotGroup.add(shadow);

  const body = new THREE.Mesh(new THREE.SphereGeometry(0.66, 32, 24), bodyMaterial);
  body.scale.set(0.9, 0.72, 0.58);
  body.position.y = -0.36;
  robotGroup.add(body);

  const chest = new THREE.Mesh(new THREE.SphereGeometry(0.28, 24, 16), trimMaterial);
  chest.scale.set(1.25, 0.72, 0.24);
  chest.position.set(0, -0.38, 0.46);
  robotGroup.add(chest);

  const head = new THREE.Group();
  head.position.y = 0.18;
  robotGroup.add(head);

  const headShell = new THREE.Mesh(new THREE.SphereGeometry(0.75, 36, 24), bodyMaterial);
  headShell.scale.set(0.96, 0.88, 0.68);
  head.add(headShell);

  const visor = new THREE.Mesh(new THREE.SphereGeometry(0.5, 32, 20), visorMaterial);
  visor.scale.set(0.96, 0.58, 0.22);
  visor.position.set(0, 0.07, 0.6);
  head.add(visor);

  const visorRim = new THREE.Mesh(new THREE.TorusGeometry(0.47, 0.025, 10, 48), ringAccentMaterial);
  visorRim.scale.y = 0.6;
  visorRim.position.set(0, 0.07, 0.66);
  head.add(visorRim);

  const eyeGeometry = new THREE.SphereGeometry(0.112, 20, 14);
  const pupilGeometry = new THREE.SphereGeometry(0.052, 16, 12);
  const eyes = [];
  const pupils = [];
  for (const x of [-0.19, 0.19]) {
    const eye = new THREE.Mesh(eyeGeometry, eyeMaterial);
    eye.scale.set(0.78, 1.18, 0.58);
    eye.position.set(x, 0.12, 0.69);
    head.add(eye);
    eyes.push(eye);

    const pupil = new THREE.Mesh(pupilGeometry, pupilMaterial);
    pupil.position.set(0, 0, 0.077);
    eye.add(pupil);
    pupils.push(pupil);
  }

  const mouth = new THREE.Line(createMouthGeometry(THREE, "idle"), mouthMaterial);
  head.add(mouth);

  const earGeometry = new THREE.TorusGeometry(0.13, 0.025, 10, 28);
  for (const x of [-0.72, 0.72]) {
    const ear = new THREE.Mesh(earGeometry, trimMaterial);
    ear.rotation.z = Math.PI / 2;
    ear.position.set(x, 0.08, 0.02);
    head.add(ear);
  }

  const antennaStem = new THREE.Mesh(new THREE.CylinderGeometry(0.016, 0.016, 0.22, 12), trimMaterial);
  antennaStem.position.y = 0.86;
  head.add(antennaStem);
  const antenna = new THREE.Mesh(new THREE.SphereGeometry(0.065, 20, 12), ringAccentMaterial);
  antenna.position.y = 0.99;
  head.add(antenna);

  const armGeometry = new THREE.SphereGeometry(0.14, 20, 14);
  for (const x of [-0.73, 0.73]) {
    const arm = new THREE.Mesh(armGeometry, trimMaterial);
    arm.scale.set(0.7, 1.45, 0.7);
    arm.position.set(x, -0.34, 0);
    robotGroup.add(arm);
  }

  const targetGaze = { x: 0, y: 0 };
  const gaze = { x: 0, y: 0 };
  let currentMouthState = "idle";

  // Calcula una mirada global para que el robot siga el cursor aunque este se
  // mueva entre el planeta, el panel y el resto del dashboard.
  const onPointerMove = (event) => {
    if (getState() === "sleep") return;
    const rect = host.getBoundingClientRect();
    targetGaze.x = clamp((event.clientX - (rect.left + rect.width / 2)) / Math.max(rect.width * 1.8, 1), -1, 1);
    targetGaze.y = clamp(((rect.top + rect.height / 2) - event.clientY) / Math.max(rect.height * 1.8, 1), -1, 1);
  };
  const resetGaze = () => { targetGaze.x = 0; targetGaze.y = 0; };
  window.addEventListener("pointermove", onPointerMove, { passive: true });
  window.addEventListener("blur", resetGaze);

  const applyState = (state) => {
    const palette = STATE_COLORS[state] || STATE_COLORS.idle;
    eyeMaterial.color.setHex(palette.eye);
    eyeMaterial.emissive.setHex(palette.emissive);
    mouthMaterial.color.setHex(palette.mouth);
    trimMaterial.color.setHex(palette.chest);
    antenna.material.color.setHex(palette.eye);
    if (currentMouthState !== state) {
      mouth.geometry.dispose();
      mouth.geometry = createMouthGeometry(THREE, state);
      currentMouthState = state;
    }
    const eyeScale = state === "sleep" ? 0.32 : 1;
    eyes.forEach((eye) => { eye.scale.y = eyeScale * 1.18; });
  };

  let visible = true;
  const visibilityObserver = new IntersectionObserver(([entry]) => { visible = entry.isIntersecting; }, { threshold: 0.02 });
  visibilityObserver.observe(host);

  const resize = () => {
    const rect = host.getBoundingClientRect();
    const width = Math.max(rect.width, 1);
    const height = Math.max(rect.height, 1);
    renderer.setSize(width, height, false);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
  };
  const resizeObserver = new ResizeObserver(resize);
  resizeObserver.observe(host);
  resize();

  const clock = new THREE.Clock();
  let previousElapsed = 0;
  let rafId = 0;
  const animate = () => {
    rafId = requestAnimationFrame(animate);
    if (!visible) return;

    const elapsed = clock.getElapsedTime();
    const delta = Math.min(Math.max(elapsed - previousElapsed, 0), 0.05);
    previousElapsed = elapsed;
    const state = getState();
    applyState(state);

    const gazeEase = Math.min(delta * 8, 1);
    gaze.x += (targetGaze.x - gaze.x) * gazeEase;
    gaze.y += (targetGaze.y - gaze.y) * gazeEase;
    head.rotation.y = gaze.x * 0.13;
    head.rotation.x = gaze.y * 0.08;
    pupils.forEach((pupil) => {
      pupil.position.x = gaze.x * 0.052;
      pupil.position.y = gaze.y * 0.035;
    });

    if (!reducedMotion) {
      const motionSpeed = state === "working" ? 1.6 : 1;
      robotGroup.position.y = -0.05 + Math.sin(elapsed * 2.2 * motionSpeed) * 0.025;
      ringAccent.rotation.z -= delta * 0.24 * motionSpeed;
      antenna.scale.setScalar(1 + Math.sin(elapsed * 3.8) * 0.1);
      eyeMaterial.emissiveIntensity = 2.45 + Math.sin(elapsed * 4.2) * 0.45;
    }

    renderer.render(scene, camera);
  };
  animate();

  return {
    setState: applyState,
    blink() {
      eyes.forEach((eye) => { eye.scale.y = 0.07; });
      window.setTimeout(() => applyState(getState()), 120);
    },
    destroy() {
      cancelAnimationFrame(rafId);
      resizeObserver.disconnect();
      visibilityObserver.disconnect();
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("blur", resetGaze);
      scene.traverse((object) => {
        object.geometry?.dispose?.();
        if (Array.isArray(object.material)) object.material.forEach((material) => material?.dispose?.());
        else object.material?.dispose?.();
      });
      renderer.dispose();
      renderer.domElement.remove();
    },
  };
}

// Conserva los estados, parpadeo y métodos públicos que ya consume el resto
// de la aplicación mientras la escena Three.js termina de cargar.
function createRobotController(robot, originalMarkup) {
  const radar = robot.closest(".execution-radar");
  const status = document.querySelector("#latest-status");
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  let state = "idle";
  let sceneHandle = null;
  let blinkTimer = 0;
  let blinkReleaseTimer = 0;
  let destroyed = false;
  let isBlinking = false;

  radar?.classList.add("utel-robot-host");

  const applyState = (nextState) => {
    if (destroyed || !ROBOT_STATES.has(nextState)) return;
    state = nextState;
    robot.dataset.state = nextState;
    sceneHandle?.setState(nextState);
  };

  const doBlink = () => {
    if (destroyed || state === "sleep" || isBlinking) return;
    isBlinking = true;
    robot.classList.add("blink");
    sceneHandle?.blink();
    blinkReleaseTimer = window.setTimeout(() => {
      if (destroyed) return;
      robot.classList.remove("blink");
      isBlinking = false;
      sceneHandle?.setState(state);
    }, 125);
  };

  const scheduleBlink = () => {
    window.clearTimeout(blinkTimer);
    if (destroyed || reducedMotion.matches) return;
    blinkTimer = window.setTimeout(() => {
      if (state !== "sleep") {
        doBlink();
        if (Math.random() < 0.18) window.setTimeout(doBlink, 260);
      }
      scheduleBlink();
    }, 2400 + Math.random() * 3400);
  };

  const statusObserver = status ? new MutationObserver(() => applyState(statusToState(status.textContent))) : null;
  statusObserver?.observe(status, { childList: true, subtree: true, characterData: true });
  applyState(statusToState(status?.textContent));
  scheduleBlink();

  const controller = {
    setState(nextState) {
      const normalized = String(nextState || "").trim().toLowerCase();
      applyState(normalized === "talking" ? "working" : normalized);
    },
    blink: doBlink,
    speak(enabled = true) { applyState(enabled ? "working" : "idle"); },
    getState() { return state; },
    destroy() {
      if (destroyed) return;
      destroyed = true;
      window.clearTimeout(blinkTimer);
      window.clearTimeout(blinkReleaseTimer);
      statusObserver?.disconnect();
      sceneHandle?.destroy();
      radar?.classList.remove("utel-robot-host");
      robot.classList.remove("blink", "utel-robot-3d", "utel-robot-fallback");
      delete robot.dataset.state;
      robot.innerHTML = originalMarkup;
      if (activeRobot === controller) activeRobot = null;
      if (window.UTELRobot === controller) delete window.UTELRobot;
    },
  };

  // La carga asíncrona mantiene el arranque del dashboard no bloqueante y
  // deja una representación de respaldo si WebGL o la red no están disponibles.
  loadThree()
    .then((THREE) => {
      if (destroyed) return;
      sceneHandle = createRobotScene(THREE, robot, () => state, reducedMotion.matches);
      sceneHandle.setState(state);
    })
    .catch((error) => {
      if (!destroyed) {
        robot.classList.add("utel-robot-fallback");
        console.warn("[Dashboard] No se pudo iniciar el robot 3D; se conserva el respaldo visual.", error);
      }
    });

  return controller;
}

export function initializeDashboardRobot() {
  if (activeRobot) return activeRobot;
  const robot = document.querySelector("#view-dashboard .execution-radar .robot-core");
  if (!robot) return null;
  installStylesheet();
  const originalMarkup = robot.innerHTML;
  activeRobot = createRobotController(robot, originalMarkup);
  window.UTELRobot = activeRobot;
  return activeRobot;
}

window.addEventListener("beforeunload", () => activeRobot?.destroy?.(), { once: true });
