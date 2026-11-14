/* FCC 3D: the small engine behind Studio's 3D views (the Trading Bank's
   debate arena and the Ops page). It keeps 3D light on the PC:

   - at most 30 frames a second (20 in low-power mode),
   - a pixel ratio of at most 1.5 (1 in low-power mode),
   - no drawing at all while the page is hidden or the view is off-screen,
   - everything freed (GPU memory included) when the page changes.

   Without WebGL, or with reduced motion switched on, stage() returns null
   and the page keeps its 2D view. three.js comes from Studio's own copy
   (vendor/three), through the import map in index.html. */
import * as THREE from "three";
import { OrbitControls } from "./three-orbit.js";

export { THREE };

let webgl = null;

export function canDraw3D() {
  if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return false;
  if (webgl === null) {
    try {
      const probe = document.createElement("canvas");
      const context = probe.getContext("webgl2") || probe.getContext("webgl");
      webgl = Boolean(context);
      context?.getExtension("WEBGL_lose_context")?.loseContext();
    } catch {
      webgl = false;
    }
  }
  return webgl;
}

// A soft round light, for halos, glows, and particles.
export function glowTexture(colour = "#ffffff") {
  const size = 64;
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = size;
  const paint = canvas.getContext("2d");
  const gradient = paint.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  gradient.addColorStop(0, colour);
  gradient.addColorStop(0.25, colour);
  gradient.addColorStop(1, "rgba(0,0,0,0)");
  paint.fillStyle = gradient;
  paint.fillRect(0, 0, size, size);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

// A text label that always faces the camera.
export function textSprite(text, colour = "#d9f6ff", { size = 0.42, weight = 600 } = {}) {
  const canvas = document.createElement("canvas");
  const paint = canvas.getContext("2d");
  const font = `${weight} 44px ui-monospace, "SF Mono", Menlo, Consolas, monospace`;
  paint.font = font;
  const width = Math.ceil(paint.measureText(text).width) + 24;
  canvas.width = width;
  canvas.height = 64;
  paint.font = font;
  paint.fillStyle = colour;
  paint.textAlign = "center";
  paint.textBaseline = "middle";
  paint.shadowColor = "rgba(0,0,0,0.85)";
  paint.shadowBlur = 8;
  paint.fillText(text, width / 2, 34);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, transparent: true, depthWrite: false }));
  sprite.scale.set((size * width) / 64, size, 1);
  return sprite;
}

/* Make a 3D view inside ``host``. Options: lowPower, camera (the direction
   to look from, [x, y, z]), fit ({ radius, height }: keep a disc of that
   radius, and things that tall, in view at any box size), fov, orbit (drag
   to turn; on by default), autoRotate, onFrame(seconds since last frame,
   seconds running), onLost. Returns { scene, camera, renderer, controls,
   dispose } or null. */
export function stage(host, options = {}) {
  if (!canDraw3D()) return null;
  const lowPower = Boolean(options.lowPower);
  const step = 1000 / (lowPower ? 20 : 30);
  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ antialias: !lowPower, alpha: true, powerPreference: "low-power" });
  } catch {
    webgl = false;
    return null;
  }
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, lowPower ? 1 : 1.5));
  renderer.setClearColor(0x000000, 0);
  const canvas = renderer.domElement;
  canvas.className = "fcc3d-canvas";
  canvas.setAttribute("aria-hidden", "true");
  host.append(canvas);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(options.fov || 42, 1, 0.1, 200);
  camera.position.set(...(options.camera || [0, 5, 9]));
  camera.lookAt(0, 0, 0);

  let controls = null;
  if (options.orbit !== false) {
    controls = new OrbitControls(camera, canvas);
    controls.enableDamping = true;
    controls.enablePan = false;
    controls.minDistance = 4;
    controls.maxDistance = 30;
    controls.maxPolarAngle = Math.PI * 0.47;
    controls.autoRotate = options.autoRotate !== false;
    controls.autoRotateSpeed = 0.5;
    // On a touch screen a finger on the view scrolls the page; the view
    // just turns slowly by itself.
    if (window.matchMedia?.("(pointer: coarse)").matches) {
      controls.enableRotate = false;
      controls.enableZoom = false;
      canvas.style.touchAction = "pan-y";
    }
  }

  // Step back far enough that the scene fits the box: wide boxes are
  // limited by height, narrow ones (a phone) by width.
  const fit = () => {
    if (!options.fit) return;
    const { radius, height = 0 } = options.fit;
    const vertical = THREE.MathUtils.degToRad(camera.fov) / 2;
    const horizontal = Math.atan(Math.tan(vertical) * camera.aspect);
    const length = camera.position.length() || 1;
    const lift = Math.asin(Math.min(1, Math.abs(camera.position.y) / length));
    const across = (radius / Math.tan(horizontal)) * 1.1;
    const tall = (radius * Math.sin(lift) + height) / Math.tan(vertical);
    const need = Math.max(across, tall);
    camera.position.setLength(need);
    if (controls) {
      controls.minDistance = need * 0.6;
      controls.maxDistance = need * 1.6;
    }
  };

  const resize = () => {
    const width = Math.max(1, host.clientWidth);
    const height = Math.max(1, host.clientHeight);
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    fit();
  };
  resize();

  let frame = 0;
  let last = 0;
  let running = 0;
  let onScreen = true;
  let stopped = false;

  const loop = (now) => {
    frame = 0;
    if (stopped || document.hidden || !onScreen) return;
    frame = requestAnimationFrame(loop);
    if (last && now - last < step - 1) return;
    const seconds = last ? Math.min(0.1, (now - last) / 1000) : 0;
    last = now;
    running += seconds;
    options.onFrame?.(seconds, running);
    controls?.update(seconds);
    renderer.render(scene, camera);
  };
  const wake = () => {
    if (!stopped && !frame && !document.hidden && onScreen) {
      last = 0;
      frame = requestAnimationFrame(loop);
    }
  };

  const sizer = new ResizeObserver(resize);
  sizer.observe(host);
  const watcher = new IntersectionObserver((entries) => {
    onScreen = entries.some((entry) => entry.isIntersecting);
    wake();
  });
  watcher.observe(host);
  document.addEventListener("visibilitychange", wake);

  const dispose = () => {
    if (stopped) return;
    stopped = true;
    cancelAnimationFrame(frame);
    sizer.disconnect();
    watcher.disconnect();
    document.removeEventListener("visibilitychange", wake);
    controls?.dispose();
    const textures = new Set();
    scene.traverse((node) => {
      node.geometry?.dispose();
      for (const material of [].concat(node.material || [])) {
        if (material.map) textures.add(material.map);
        material.dispose();
      }
    });
    for (const texture of textures) texture.dispose();
    renderer.dispose();
    renderer.forceContextLoss();
    canvas.remove();
  };

  canvas.addEventListener("webglcontextlost", (event) => {
    event.preventDefault();
    if (stopped) return; // our own clean-up, not a lost card
    dispose();
    options.onLost?.();
  });

  wake();
  return { scene, camera, renderer, controls, dispose, lowPower };
}
