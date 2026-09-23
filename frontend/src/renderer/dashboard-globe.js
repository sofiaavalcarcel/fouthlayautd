"use strict";

import { HOLLOW_GLOBE_LAND_TEXTURE } from "./dashboard-globe-land.js?v=hollow-arcs-4";
import { HOLLOW_GLOBE_ROUTES, HOLLOW_GLOBE_HUBS } from "./dashboard-globe-data.js?v=hollow-arcs-4";
import { loadThree } from "./three-runtime.js?v=utel-scenes-1";

const STYLE_ID = "dashboard-globe-three-style";
let activeGlobe = null;

// Renderiza el canvas con una densidad superior a la del layout CSS. El
// canvas se amplía ligeramente para que el planeta sobresalga del panel, por
// eso una resolución interna mayor evita el pixelado sin alterar su tamaño.
const GLOBE_RENDER_SCALE = 1.5;
function getGlobePixelRatio() {
  const deviceRatio = Math.max(window.devicePixelRatio || 1, 1);
  return Math.min(deviceRatio * GLOBE_RENDER_SCALE, 3);
}

function installStylesheet() {
  if (document.getElementById(STYLE_ID)) return;
  const link = document.createElement("link");
  link.id = STYLE_ID;
  link.rel = "stylesheet";
  link.href = new URL("./dashboard-globe.css?v=hollow-arcs-4", import.meta.url).href;
  document.head.appendChild(link);
}

function makeGlowTexture(THREE) {
  const size = 128;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const context = canvas.getContext("2d");
  const gradient = context.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  gradient.addColorStop(0, "rgba(255,255,255,1)");
  gradient.addColorStop(0.2, "rgba(255,255,255,.95)");
  gradient.addColorStop(0.45, "rgba(180,255,255,.45)");
  gradient.addColorStop(1, "rgba(255,255,255,0)");
  context.fillStyle = gradient;
  context.fillRect(0, 0, size, size);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

function createDashboardGlobe(THREE, container) {
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const scene = new THREE.Scene();
  scene.fog = new THREE.Fog(0x122315, 7.5, 13.5);

  const camera = new THREE.PerspectiveCamera(46, 1, 0.1, 100);
  camera.position.set(0.7, 0.4, 5.45);
  camera.lookAt(0, 0, 0);

  const renderer = new THREE.WebGLRenderer({
    antialias: true,
    alpha: true,
    powerPreference: "high-performance",
  });
  renderer.setClearColor(0x000000, 0);
  renderer.setPixelRatio(getGlobePixelRatio());
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.08;
  renderer.domElement.setAttribute("aria-hidden", "true");
  renderer.domElement.tabIndex = -1;
  container.appendChild(renderer.domElement);

  const globeGroup = new THREE.Group();
  globeGroup.rotation.set(-0.035, -0.34, -0.02);
  scene.add(globeGroup);

  scene.add(new THREE.AmbientLight(0x9fe770, 0.72));
  const dir1 = new THREE.DirectionalLight(0x06b706, 1.45);
  dir1.position.set(5, 2, 5);
  scene.add(dir1);
  const dir2 = new THREE.DirectionalLight(0x4000bc, 0.78);
  dir2.position.set(-4, -1, 3);
  scene.add(dir2);
  const dir3 = new THREE.DirectionalLight(0xffb937, 0.36);
  dir3.position.set(0, 5, -4);
  scene.add(dir3);

  const spriteTexture = makeGlowTexture(THREE);
  const landTexture = new THREE.TextureLoader().load(
    HOLLOW_GLOBE_LAND_TEXTURE,
    (texture) => {
      texture.colorSpace = THREE.SRGBColorSpace;
      texture.wrapS = THREE.RepeatWrapping;
      texture.wrapT = THREE.ClampToEdgeWrapping;
      texture.anisotropy = Math.min(renderer.capabilities.getMaxAnisotropy(), 8);
    },
    undefined,
    (error) => console.warn("[Dashboard] No se pudo cargar la máscara Hollow Globe.", error),
  );
  landTexture.colorSpace = THREE.SRGBColorSpace;
  landTexture.wrapS = THREE.RepeatWrapping;
  landTexture.wrapT = THREE.ClampToEdgeWrapping;

  const globeRadius = 1.55;

  // Retícula espacial: hace perceptible la curvatura de la esfera incluso
  // cuando el mapa de continentes está girando o queda en sombra.
  const gridGeometry = new THREE.WireframeGeometry(new THREE.SphereGeometry(globeRadius * 1.008, 36, 18));
  const grid = new THREE.LineSegments(
    gridGeometry,
    new THREE.LineBasicMaterial({
      color: 0x9fe770,
      transparent: true,
      opacity: 0.13,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      depthTest: false,
    }),
  );
  globeGroup.add(grid);

  globeGroup.add(new THREE.Mesh(
    new THREE.SphereGeometry(globeRadius, 112, 112),
    new THREE.MeshPhysicalMaterial({
      color: 0x020a11,
      transparent: true,
      opacity: 0.28,
      roughness: 0.45,
      metalness: 0.15,
      transmission: 0.02,
      reflectivity: 0.35,
      depthWrite: false,
    }),
  ));

  const continentsMaterial = new THREE.ShaderMaterial({
    uniforms: {
      uMap: { value: landTexture },
      uCameraPos: { value: new THREE.Vector3() },
      uGreen: { value: new THREE.Color(0x9fe770) },
      uPurple: { value: new THREE.Color(0x4000bc) },
    },
    transparent: true,
    side: THREE.DoubleSide,
    depthWrite: false,
    vertexShader: `
      varying vec2 vUv;
      varying vec3 vNormalW;
      varying vec3 vWorldPos;
      void main() {
        vUv = uv;
        vNormalW = normalize(mat3(modelMatrix) * normal);
        vec4 wp = modelMatrix * vec4(position, 1.0);
        vWorldPos = wp.xyz;
        gl_Position = projectionMatrix * viewMatrix * wp;
      }
    `,
    fragmentShader: `
      uniform sampler2D uMap;
      uniform vec3 uCameraPos;
      uniform vec3 uGreen;
      uniform vec3 uPurple;
      varying vec2 vUv;
      varying vec3 vNormalW;
      varying vec3 vWorldPos;
      float luma(vec3 c) { return dot(c, vec3(0.299, 0.587, 0.114)); }
      void main() {
        vec4 tex = texture2D(uMap, vUv);
        float mask = smoothstep(0.08, 0.18, luma(tex.rgb));
        if (mask < 0.12) discard;
        vec3 V = normalize(uCameraPos - vWorldPos);
        float fres = pow(1.0 - max(dot(normalize(vNormalW), V), 0.0), 2.6);
        float purpleBand = smoothstep(0.15, 0.9, sin(vUv.y * 12.0 + vUv.x * 3.0) * 0.5 + 0.5) * 0.18;
        vec3 base = mix(vec3(0.05, 0.13, 0.06), uGreen, 0.30 + fres * 0.52);
        base = mix(base, uPurple, purpleBand * fres);
        gl_FragColor = vec4(base * (0.55 + fres * 1.15), 0.88);
      }
    `,
  });
  globeGroup.add(new THREE.Mesh(
    new THREE.SphereGeometry(globeRadius * 1.003, 112, 112),
    continentsMaterial,
  ));

  const shellMaterial = new THREE.ShaderMaterial({
    uniforms: {
      uColor: { value: new THREE.Color(0x06b706) },
      uGold: { value: new THREE.Color(0xffb937) },
      uCameraPos: { value: new THREE.Vector3() },
    },
    transparent: true,
    side: THREE.BackSide,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
    vertexShader: `
      varying vec3 vNormalW;
      varying vec3 vWorldPos;
      void main() {
        vNormalW = normalize(mat3(modelMatrix) * normal);
        vec4 wp = modelMatrix * vec4(position, 1.0);
        vWorldPos = wp.xyz;
        gl_Position = projectionMatrix * viewMatrix * wp;
      }
    `,
    fragmentShader: `
      uniform vec3 uColor;
      uniform vec3 uGold;
      uniform vec3 uCameraPos;
      varying vec3 vNormalW;
      varying vec3 vWorldPos;
      void main() {
        vec3 V = normalize(uCameraPos - vWorldPos);
        float fres = pow(1.0 - max(dot(-normalize(vNormalW), V), 0.0), 3.0);
        float band = smoothstep(0.2, 0.8, vWorldPos.y * 0.2 + 0.5);
        vec3 col = mix(uGold, uColor, band);
        gl_FragColor = vec4(col, fres * 0.45);
      }
    `,
  });
  globeGroup.add(new THREE.Mesh(
    new THREE.SphereGeometry(globeRadius * 1.04, 88, 88),
    shellMaterial,
  ));

  // Segunda capa de atmósfera: aporta volumen alrededor de los nodos sin
  // competir con las rutas que deben permanecer en primer plano.
  globeGroup.add(new THREE.Mesh(
    new THREE.SphereGeometry(globeRadius * 1.075, 72, 72),
    new THREE.MeshBasicMaterial({
      color: 0x06b706,
      transparent: true,
      opacity: 0.08,
      side: THREE.BackSide,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    }),
  ));

  function latLngToVec3(lat, lng, radius) {
    const phi = (90 - lat) * Math.PI / 180;
    const theta = (lng + 180) * Math.PI / 180;
    return new THREE.Vector3(
      -(radius * Math.sin(phi) * Math.cos(theta)),
      radius * Math.cos(phi),
      radius * Math.sin(phi) * Math.sin(theta),
    );
  }

  const arcGroup = new THREE.Group();
  globeGroup.add(arcGroup);
  const movingPulses = [];

  function createNode(position, color, size = 0.11) {
    const sprite = new THREE.Sprite(new THREE.SpriteMaterial({
      map: spriteTexture,
      color: new THREE.Color(color),
      transparent: true,
      opacity: 0.95,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    }));
    sprite.scale.set(size, size, size);
    sprite.position.copy(position);
    arcGroup.add(sprite);
    return sprite;
  }

  function createArc(route, index) {
    const start = latLngToVec3(route.s[0], route.s[1], globeRadius * 1.03);
    const end = latLngToVec3(route.e[0], route.e[1], globeRadius * 1.03);
    const midpoint = start.clone().add(end).normalize().multiplyScalar(globeRadius * (1.15 + route.h));
    const curve = new THREE.QuadraticBezierCurve3(start, midpoint, end);
    const points = curve.getPoints(180);

    arcGroup.add(new THREE.Line(
      new THREE.BufferGeometry().setFromPoints(points),
      new THREE.LineBasicMaterial({
        color: new THREE.Color(route.c),
        transparent: true,
        opacity: route.c === "#4000bc" ? 0.85 : 0.72,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
      }),
    ));
    arcGroup.add(new THREE.Line(
      new THREE.BufferGeometry().setFromPoints(points),
      new THREE.LineBasicMaterial({
        color: 0x9fe770,
        transparent: true,
        opacity: 0.12,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
      }),
    ));

    createNode(start, route.c, 0.09);
    createNode(end, route.c, 0.09);

    // Dos pulsos por ruta generan la lectura de tráfico continuo sin llenar
    // la escena de partículas estáticas: uno principal y otro de seguimiento.
    const pulseColor = route.c;
    const pulseSize = route.c === "#4000bc" ? 0.16 : 0.13;
    const createPulse = (color, size, baseOpacity, phaseOffset) => {
      const pulse = createNode(start.clone(), color, size);
      pulse.userData = {
        curve,
        speed: 0.22 + Math.random() * 0.18,
        t: (Math.random() + phaseOffset) % 1,
        scaleBase: size,
        baseOpacity,
      };
      movingPulses.push(pulse);
    };
    createPulse(pulseColor, pulseSize, 0.98, 0);
    createPulse("#9fe770", 0.072, 0.58, 0.38 + index * 0.017);
  }

  HOLLOW_GLOBE_ROUTES.forEach(createArc);
  const hubSprites = HOLLOW_GLOBE_HUBS.map(([lat, lng, color, size]) => (
    createNode(latLngToVec3(lat, lng, globeRadius * 1.035), color, size)
  ));

  const ringGeometry = new THREE.TorusGeometry(globeRadius * 1.17, 0.006, 12, 220);
  const ring = new THREE.Mesh(
    ringGeometry,
    new THREE.MeshBasicMaterial({
      color: 0x06b706,
      transparent: true,
      opacity: 0.18,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    }),
  );
  ring.rotation.x = Math.PI * 0.28;
  ring.rotation.y = Math.PI * 0.08;
  globeGroup.add(ring);

  const ring2 = new THREE.Mesh(
    ringGeometry.clone(),
    new THREE.MeshBasicMaterial({
      color: 0x4000bc,
      transparent: true,
      opacity: 0.11,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    }),
  );
  ring2.scale.set(1.05, 1.05, 1.05);
  ring2.rotation.x = -Math.PI * 0.4;
  ring2.rotation.y = Math.PI * 0.48;
  globeGroup.add(ring2);

  const ring3 = new THREE.Mesh(
    ringGeometry.clone(),
    new THREE.MeshBasicMaterial({
      color: 0xffb937,
      transparent: true,
      opacity: 0.11,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    }),
  );
  ring3.scale.set(1.09, 1.09, 1.09);
  ring3.rotation.x = Math.PI * 0.48;
  ring3.rotation.y = -Math.PI * 0.28;
  globeGroup.add(ring3);

  let autoRotate = !reducedMotion;
  let dragging = false;
  let previousPointerX = 0;
  let previousPointerY = 0;

  const onPointerDown = (event) => {
    dragging = true;
    previousPointerX = event.clientX;
    previousPointerY = event.clientY;
    container.classList.add("is-dragging");
    container.setPointerCapture?.(event.pointerId);
  };
  const onPointerMove = (event) => {
    if (!dragging) return;
    globeGroup.rotation.y += (event.clientX - previousPointerX) * 0.006;
    globeGroup.rotation.x += (event.clientY - previousPointerY) * 0.0045;
    globeGroup.rotation.x = THREE.MathUtils.clamp(globeGroup.rotation.x, -0.8, 0.8);
    previousPointerX = event.clientX;
    previousPointerY = event.clientY;
  };
  const onPointerUp = (event) => {
    dragging = false;
    container.classList.remove("is-dragging");
    container.releasePointerCapture?.(event.pointerId);
  };
  const onWheel = (event) => {
    event.preventDefault();
    const next = THREE.MathUtils.clamp(camera.position.length() + event.deltaY * 0.0035, 4.45, 7.2);
    camera.position.setLength(next);
    camera.lookAt(0, 0, 0);
  };
  const onDoubleClick = () => {
    if (!reducedMotion) autoRotate = !autoRotate;
  };

  container.addEventListener("pointerdown", onPointerDown);
  container.addEventListener("pointermove", onPointerMove);
  container.addEventListener("pointerup", onPointerUp);
  container.addEventListener("pointercancel", onPointerUp);
  container.addEventListener("wheel", onWheel, { passive: false });
  container.addEventListener("dblclick", onDoubleClick);

  const resize = () => {
    const rect = container.getBoundingClientRect();
    const width = Math.max(rect.width, 1);
    const height = Math.max(rect.height, 1);
    renderer.setSize(width, height, false);
    renderer.setPixelRatio(getGlobePixelRatio());
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
  };
  const resizeObserver = new ResizeObserver(resize);
  resizeObserver.observe(container);
  resize();

  let visible = true;
  const visibilityObserver = new IntersectionObserver(
    ([entry]) => { visible = entry.isIntersecting; },
    { threshold: 0.02 },
  );
  visibilityObserver.observe(container);

  const clock = new THREE.Clock();
  let previousElapsed = 0;
  let rafId = 0;

  const animate = () => {
    rafId = requestAnimationFrame(animate);
    if (!visible) return;

    const elapsed = clock.getElapsedTime();
    const delta = Math.min(Math.max(elapsed - previousElapsed, 0), 0.05);
    previousElapsed = elapsed;
    continentsMaterial.uniforms.uCameraPos.value.copy(camera.position);
    shellMaterial.uniforms.uCameraPos.value.copy(camera.position);

    if (!reducedMotion) {
      if (autoRotate && !dragging) globeGroup.rotation.y += 0.108 * delta;
      ring.rotation.z += 0.09 * delta;
      ring2.rotation.z -= 0.066 * delta;
      ring3.rotation.z += 0.045 * delta;

      movingPulses.forEach((sprite, index) => {
        sprite.userData.t = (sprite.userData.t + sprite.userData.speed * delta * 0.62) % 1;
        sprite.position.copy(sprite.userData.curve.getPoint(sprite.userData.t));
        const scale = sprite.userData.scaleBase * (1 + Math.sin(elapsed * 4 + index) * 0.18);
        sprite.scale.set(scale, scale, scale);
        sprite.material.opacity = sprite.userData.baseOpacity * (0.70 + 0.30 * Math.sin(elapsed * 5 + index * 0.7));
      });

      hubSprites.forEach((hub, index) => {
        const pulse = 1 + Math.sin(elapsed * 2.2 + index) * 0.14;
        const base = HOLLOW_GLOBE_HUBS[index][3];
        hub.scale.set(base * pulse, base * pulse, base * pulse);
        hub.material.opacity = 0.78 + Math.sin(elapsed * 3 + index) * 0.16;
      });
    }

    renderer.render(scene, camera);
  };
  animate();

  return {
    destroy() {
      cancelAnimationFrame(rafId);
      resizeObserver.disconnect();
      visibilityObserver.disconnect();
      container.removeEventListener("pointerdown", onPointerDown);
      container.removeEventListener("pointermove", onPointerMove);
      container.removeEventListener("pointerup", onPointerUp);
      container.removeEventListener("pointercancel", onPointerUp);
      container.removeEventListener("wheel", onWheel);
      container.removeEventListener("dblclick", onDoubleClick);
      scene.traverse((object) => {
        object.geometry?.dispose?.();
        if (Array.isArray(object.material)) object.material.forEach((material) => material?.dispose?.());
        else object.material?.dispose?.();
      });
      spriteTexture.dispose();
      landTexture.dispose();
      renderer.dispose();
      renderer.domElement.remove();
    },
  };
}

export async function initializeDashboardGlobe() {
  const container = document.querySelector("#view-dashboard .dashboard-globe");
  if (!container || activeGlobe) return;

  const legacyMarkup = container.innerHTML;
  installStylesheet();
  try {
    const THREE = await loadThree();
    container.classList.add("three-globe-active", "hollow-arcs-active");
    container.replaceChildren();
    activeGlobe = createDashboardGlobe(THREE, container);
    console.info("[Dashboard] Globo 3D Hollow + Arcs activo.");
  } catch (error) {
    container.classList.remove("three-globe-active", "hollow-arcs-active");
    container.innerHTML = legacyMarkup;
    console.warn("[Dashboard] No se pudo iniciar Hollow + Arcs; se conserva el planeta CSS.", error);
  }
}

window.addEventListener("beforeunload", () => activeGlobe?.destroy?.(), { once: true });
