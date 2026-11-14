// Shared pieces for the Lab box's 3D: meshes, materials, canvas textures,
// labels and a soft glow. All FCC's own code on three.js.
import * as THREE from "three";

export { THREE };

/** A mesh that casts and takes shadows, placed at x, y, z. */
export function mesh(geometry, material, x = 0, y = 0, z = 0) {
  const item = new THREE.Mesh(geometry, material);
  item.position.set(x, y, z);
  item.castShadow = true;
  item.receiveShadow = true;
  return item;
}

/** A box whose bottom sits at y (not its middle). */
export const block = (w, h, d, material, x = 0, y = 0, z = 0) => mesh(new THREE.BoxGeometry(w, h, d), material, x, y + h / 2, z);

/** An upright cylinder whose bottom sits at y. */
export const post = (radius, h, material, x = 0, y = 0, z = 0, segments = 20) => mesh(new THREE.CylinderGeometry(radius, radius, h, segments), material, x, y + h / 2, z);

export const standard = (color, roughness = 0.6, metalness = 0, extra = {}) => new THREE.MeshStandardMaterial({ color, roughness, metalness, ...extra });
export const metal = (color = "#c9ccd1", roughness = 0.3) => standard(color, roughness, 1);
export const glow = (color, intensity = 1.5) => new THREE.MeshStandardMaterial({ color, emissive: color, emissiveIntensity: intensity, roughness: 0.4 });

/** A texture drawn on a canvas; draw(paint, width, height). */
export function canvasTexture(width, height, draw, { repeat = null } = {}) {
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  draw(canvas.getContext("2d"), width, height);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = 4;
  if (repeat) {
    texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
    texture.repeat.set(repeat[0], repeat[1]);
  }
  return texture;
}

/** A circuit board's face: solder mask, copper traces, silkscreen text. */
export function boardTexture(colour, label = "", { traces = 14, seed = 3 } = {}) {
  return canvasTexture(256, 160, (paint, w, h) => {
    paint.fillStyle = colour;
    paint.fillRect(0, 0, w, h);
    let value = seed * 9301 + 49297;
    const random = () => ((value = (value * 9301 + 49297) % 233280) / 233280);
    paint.strokeStyle = "rgba(255,255,255,0.13)";
    paint.lineWidth = 2;
    for (let i = 0; i < traces; i += 1) {
      paint.beginPath();
      let x = random() * w;
      let y = random() * h;
      paint.moveTo(x, y);
      for (let step = 0; step < 3; step += 1) {
        if (step % 2) y = random() * h;
        else x = random() * w;
        paint.lineTo(x, y);
      }
      paint.stroke();
    }
    paint.fillStyle = "rgba(255,215,120,0.55)";
    for (let i = 0; i < 26; i += 1) {
      paint.beginPath();
      paint.arc(random() * w, random() * h, 2.2, 0, Math.PI * 2);
      paint.fill();
    }
    if (label) {
      paint.fillStyle = "rgba(255,255,255,0.85)";
      paint.font = "bold 26px sans-serif";
      paint.textAlign = "center";
      paint.fillText(label, w / 2, h / 2 + 9);
    }
  });
}

/** A label: text on a rounded tag, always facing the camera. */
export function label(text, { color = "#ffffff", background = "rgba(15,20,28,0.78)", height = 0.32, bold = true } = {}) {
  const font = `${bold ? "600 " : ""}44px system-ui, -apple-system, sans-serif`;
  const probe = document.createElement("canvas").getContext("2d");
  probe.font = font;
  const width = Math.ceil(probe.measureText(text).width) + 48;
  const texture = canvasTexture(width, 72, (paint, w, h) => {
    paint.fillStyle = background;
    paint.beginPath();
    // roundRect needs iOS 16; older Safari gets square corners, not a crash.
    if (paint.roundRect) paint.roundRect(2, 2, w - 4, h - 4, 30);
    else paint.rect(2, 2, w - 4, h - 4);
    paint.fill();
    paint.font = font;
    paint.fillStyle = color;
    paint.textAlign = "center";
    paint.textBaseline = "middle";
    paint.fillText(text, w / 2, h / 2 + 2);
  });
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, transparent: true, depthWrite: false, depthTest: false }));
  sprite.scale.set((height * width) / 72, height, 1);
  sprite.renderOrder = 10;
  sprite.userData.label = true;
  return sprite;
}

let glowTexture = null;
/** A soft round glow (additive), for LEDs, bulbs and flames. */
export function glowSprite(color, size = 1) {
  glowTexture =
    glowTexture ||
    canvasTexture(64, 64, (paint, w, h) => {
      const gradient = paint.createRadialGradient(w / 2, h / 2, 0, w / 2, h / 2, w / 2);
      gradient.addColorStop(0, "rgba(255,255,255,1)");
      gradient.addColorStop(0.25, "rgba(255,255,255,0.55)");
      gradient.addColorStop(1, "rgba(255,255,255,0)");
      paint.fillStyle = gradient;
      paint.fillRect(0, 0, w, h);
    });
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTexture, color, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending }));
  sprite.scale.setScalar(size);
  sprite.userData.keepTexture = true;
  return sprite;
}

/** A soft puff texture (steam, smoke, gas). */
export const puffTexture = () =>
  canvasTexture(64, 64, (paint, w, h) => {
    const gradient = paint.createRadialGradient(w / 2, h / 2, 0, w / 2, h / 2, w / 2);
    gradient.addColorStop(0, "rgba(255,255,255,0.9)");
    gradient.addColorStop(0.6, "rgba(255,255,255,0.35)");
    gradient.addColorStop(1, "rgba(255,255,255,0)");
    paint.fillStyle = gradient;
    paint.fillRect(0, 0, w, h);
  });

/** A thin tube along points (a wire or a pipe); returns [mesh, curve]. */
export function tube(points, radius, material, segments = 40) {
  const curve = new THREE.CatmullRomCurve3(points.map((point) => (point.isVector3 ? point : new THREE.Vector3(...point))));
  const item = mesh(new THREE.TubeGeometry(curve, segments, radius, 8, false), material);
  return [item, curve];
}

/** Free everything a group holds (geometry, materials, textures). */
export function dispose(root) {
  root.traverse((child) => {
    if (child.geometry) child.geometry.dispose();
    for (const material of [child.material].flat()) {
      if (!material) continue;
      for (const value of Object.values(material)) if (value && value.isTexture && !child.userData.keepTexture) value.dispose();
      material.dispose();
    }
  });
}

/** Mark an object as something the user can tap (what = data for the tap). */
export function pickable(object, what) {
  object.userData.pick = what;
  return object;
}
