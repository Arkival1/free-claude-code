// Jarvis in the Lab box: a small friendly robot (FCC's own model, built from
// shapes) who walks to the room a job needs and works at its bench. Poses:
// idle, walk, work, think, wave. Units: the box's (about a metre each).
import { THREE, mesh, standard, glow, label } from "./look3d.js";

export function makeJarvis() {
  const root = new THREE.Group();
  const shell = new THREE.MeshPhysicalMaterial({ color: "#f4f6f8", roughness: 0.25, clearcoat: 1, clearcoatRoughness: 0.1 });
  const dark = standard("#1c2128", 0.35, 0.2);
  const light = glow("#5fe1ff", 2.2);
  const body = new THREE.Group();
  body.position.y = 0.42;
  root.add(body);
  body.add(mesh(new THREE.CapsuleGeometry(0.22, 0.3, 8, 20), shell, 0, 0.27, 0));
  const ring = mesh(new THREE.TorusGeometry(0.09, 0.022, 8, 24), light, 0, 0.33, 0.2);
  body.add(ring);
  body.add(mesh(new THREE.CylinderGeometry(0.2, 0.17, 0.08, 20), dark, 0, 0.02, 0));
  const head = new THREE.Group();
  head.position.y = 0.66;
  body.add(head);
  const skull = mesh(new THREE.SphereGeometry(0.21, 24, 18), shell, 0, 0.12, 0);
  skull.scale.set(1.12, 0.92, 1);
  head.add(skull);
  const visor = mesh(new THREE.SphereGeometry(0.2, 24, 12, -0.9, 1.8, 1.1, 0.9), dark, 0, 0.11, 0.035);
  visor.scale.set(1.1, 0.95, 1);
  head.add(visor);
  const eyes = [-0.07, 0.07].map((x) => {
    const eye = mesh(new THREE.CapsuleGeometry(0.022, 0.03, 4, 8), light, x, 0.12, 0.215);
    head.add(eye);
    return eye;
  });
  for (const x of [-0.235, 0.235]) {
    const ear = mesh(new THREE.CylinderGeometry(0.045, 0.045, 0.04, 16), light, x, 0.12, 0);
    ear.rotation.z = Math.PI / 2;
    head.add(ear);
  }
  head.add(mesh(new THREE.CylinderGeometry(0.008, 0.008, 0.12, 6), dark, 0, 0.36, 0));
  const tip = mesh(new THREE.SphereGeometry(0.025, 10, 8), light, 0, 0.43, 0);
  head.add(tip);
  const limb = (x, y, length, radius) => {
    const pivot = new THREE.Group();
    pivot.position.set(x, y, 0);
    pivot.add(mesh(new THREE.CapsuleGeometry(radius, length, 6, 12), shell, 0, -length / 2 - radius, 0));
    const end = mesh(new THREE.SphereGeometry(radius * 1.25, 12, 10), dark, 0, -length - radius * 2, 0);
    pivot.add(end);
    return pivot;
  };
  const arms = [limb(-0.29, 0.42, 0.2, 0.055), limb(0.29, 0.42, 0.2, 0.055)];
  for (const arm of arms) body.add(arm);
  const legs = [limb(-0.1, 0.02, 0.17, 0.065), limb(0.1, 0.02, 0.17, 0.065)];
  for (const leg of legs) body.add(leg);
  const name = label("Jarvis", { height: 0.13, background: "rgba(10,60,80,0.8)" });
  name.position.y = 1.45;
  root.add(name);
  let bubble = null;

  /** Pose for this frame: idle, walk, work, think or wave. */
  function pose(state, t) {
    const swing = Math.sin(t * 7.5);
    body.position.y = 0.42 + (state === "walk" ? Math.abs(swing) * 0.03 : Math.sin(t * 2) * 0.008);
    head.rotation.set(0, 0, 0);
    arms[0].rotation.set(0, 0, 0.12);
    arms[1].rotation.set(0, 0, -0.12);
    legs[0].rotation.set(0, 0, 0);
    legs[1].rotation.set(0, 0, 0);
    if (state === "walk") {
      legs[0].rotation.x = swing * 0.55;
      legs[1].rotation.x = -swing * 0.55;
      arms[0].rotation.x = -swing * 0.5;
      arms[1].rotation.x = swing * 0.5;
    } else if (state === "work") {
      head.rotation.x = 0.35;
      arms[0].rotation.x = -1.1 + Math.sin(t * 5) * 0.18;
      arms[1].rotation.x = -1.1 + Math.sin(t * 5 + 1.7) * 0.18;
      arms[0].rotation.z = 0.25;
      arms[1].rotation.z = -0.25;
    } else if (state === "think") {
      head.rotation.set(-0.1, Math.sin(t * 0.8) * 0.2, 0.12);
      arms[1].rotation.set(-2.2, 0, -0.5);
    } else if (state === "wave") {
      arms[1].rotation.set(0, 0, -2.6 + Math.sin(t * 8) * 0.35);
      head.rotation.y = Math.sin(t * 1.5) * 0.15;
    } else head.rotation.y = Math.sin(t * 0.6) * 0.35;
    const blink = Math.sin(t * 1.3) > 0.985 ? 0.1 : 1;
    for (const eye of eyes) eye.scale.y = blink;
    tip.material.emissiveIntensity = 1.5 + Math.sin(t * 4) * 1;
    ring.material.emissiveIntensity = state === "work" ? 2.5 + Math.sin(t * 9) : 2.2;
  }

  /** A speech bubble over his head (empty clears it). */
  function say(text) {
    if (bubble) {
      root.remove(bubble);
      bubble.material.map.dispose();
      bubble.material.dispose();
      bubble = null;
    }
    if (!text) return;
    bubble = label(text.length > 42 ? `${text.slice(0, 40)}…` : text, { height: 0.15, background: "rgba(255,255,255,0.92)", color: "#14202b", bold: false });
    bubble.position.y = 1.68;
    root.add(bubble);
  }

  return { root, pose, say };
}
