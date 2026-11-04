// The Lab screen: the 3D Lab box (views/workshop.js) and its Game kit room,
// where you see what the kit makes, live in 3D (textures, shaders, models,
// animation), start a 3D game from the starter, or ask the AI for one. The AI
// builds 3D games with this same kit.
import { state } from "../state.js";
import { el, button, card, notify, go, openSheet, closeSheet } from "../ui.js";
import { createProject, writeFile } from "../projects.js";
import { game3dFiles } from "../lab.js";
import { addToLibrary } from "../library.js";
import { render as renderBox } from "./workshop.js";

const SHELVES = {
  textures: { label: "Textures", items: ["stone", "wood", "grass", "metal", "lava", "sand", "bark", "ice"] },
  shaders: { label: "Shaders", items: ["fire", "embers", "water", "glow", "toon", "dissolve"] },
  models: { label: "Models", items: ["warrior", "boss", "tree", "burning tree", "rock", "tower", "sword"] },
  animation: { label: "Animation", items: ["idle", "walk", "run", "attack", "heavy", "roll", "hit", "dead"] },
};
const LOOP = { attack: 1.2, heavy: 1.8, roll: 1.1, hit: 0.9, dead: 2.4 };

function startGameSheet() {
  const name = el("input", { "aria-label": "The game's name", placeholder: "Ember Temple" });
  openSheet("Start a 3D game", [
    el("p", { class: "small muted", text: "A third-person action game that already plays: a warrior, a boss with telegraphed blows, a bonfire, fire and fog. Then ask the AI to make it yours." }),
    el("label", {}, ["Name", name]),
    button("Start it", async () => {
      try {
        const project = await createProject(name.value.trim() || "3D game");
        if (!Object.keys(project.files).length) {
          for (const [path, body] of Object.entries(await game3dFiles(project.name))) await writeFile(project, path, body, "you");
        }
        closeSheet();
        notify(`${project.name} is ready to play.`);
        go(`projects/${project.id}`);
      } catch (error) {
        notify(error.message);
      }
    }, { class: "primary" }),
  ]);
}

/** The Lab: the 3D box (#lab), or the Game kit room (#lab/game). */
export function render(view, param) {
  return param === "game" ? renderGameKit(view) : renderBox(view);
}

/** The Game kit: the 3D game-making kit, live, and the 3D game starter. */
function renderGameKit(view) {
  let shelf = "models";
  let item = "warrior";
  let stage = null;
  const caption = el("p", { class: "small muted lab-caption" });
  const canvas = el("canvas", { class: "lab-stage", "aria-label": "Lab preview" });
  const tabs = el("div", { class: "lab-tabs", role: "group", "aria-label": "What to look at" });
  const chips = el("div", { class: "lab-chips", role: "group", "aria-label": "Items" });
  const actions = el("div", { class: "row" });

  const draw = () => {
    tabs.replaceChildren(
      ...Object.entries(SHELVES).map(([key, entry]) =>
        el("button", { class: "lib-filter", type: "button", "aria-pressed": String(key === shelf), text: entry.label, onclick: () => {
          shelf = key;
          item = SHELVES[key].items[0];
          draw();
        } })
      )
    );
    chips.replaceChildren(
      ...SHELVES[shelf].items.map((name) =>
        el("button", { class: "lab-chip", type: "button", "aria-pressed": String(name === item), text: name, onclick: () => {
          item = name;
          draw();
        } })
      )
    );
    actions.replaceChildren(
      ...(shelf === "textures"
        ? [
            button("Save to library", async () => {
              if (!stage) return;
              await addToLibrary({ kind: "photo", title: `${item} texture`, notes: `The Lab's ${item} texture (lab/kit.js makeTexture("${item}")).`, image: stage.textureImage(item) });
              notify(`The ${item} texture is in your library.`);
            }),
          ]
        : [])
    );
    if (stage) caption.textContent = stage.show(shelf, item);
  };

  view.replaceChildren(
    card("Game Lab", [
      el("p", { text: "3D games made in code: textures, shaders, models and animation, all original. The AI builds 3D games with this kit, and makes its own new pieces the same way." }),
      el("div", { class: "row" }, [
        button("⟵ Lab box", () => go("lab")),
        button("Start a 3D game", startGameSheet, { class: "primary" }),
        button("Ask the AI for one", () => {
          state.labAsk = "a 3D third-person game where ";
          go("home");
        }),
      ]),
    ]),
    tabs,
    el("div", { class: "card lab-card" }, [canvas, caption, chips, actions])
  );

  let stopped = false;
  (async () => {
    try {
      const THREE = await import("three");
      const Lab = await import("../../lab/kit.js");
      if (stopped) return;
      stage = makeStage(THREE, Lab, canvas);
      draw();
    } catch (error) {
      caption.textContent = `3D can't start on this device: ${error.message}`;
      draw();
    }
  })();
  draw();
  return () => {
    stopped = true;
    if (stage) stage.stop();
  };
}

/** The live preview: one scene, one subject at a time, turning slowly. */
function makeStage(THREE, Lab, canvas) {
  const renderer = Lab.makeRenderer(canvas, { maxPixelRatio: 1.5 });
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 500);
  Lab.addLights(scene, { density: 0.018 });
  scene.add(Lab.makeSky());
  const floor = new THREE.Mesh(new THREE.CircleGeometry(9, 48), Lab.makeMaterial("stone", { repeat: 3 }));
  floor.rotation.x = -Math.PI / 2;
  floor.receiveShadow = true;
  scene.add(floor);
  let subject = new THREE.Group();
  scene.add(subject);
  let animated = [];
  let pose = null;
  let dissolve = null;
  let frame = 0;
  let focus = new THREE.Vector3(0, 1, 0);
  let distance = 5;

  const clear = () => {
    scene.remove(subject);
    subject.traverse((child) => {
      if (child.geometry) child.geometry.dispose();
      for (const material of [child.material].flat()) {
        if (!material) continue;
        for (const value of Object.values(material)) if (value && value.isTexture) value.dispose();
        for (const uniform of Object.values(material.uniforms || {})) if (uniform.value && uniform.value.isTexture) uniform.value.dispose();
        material.dispose();
      }
    });
    subject = new THREE.Group();
    scene.add(subject);
    animated = [];
    pose = null;
    dissolve = null;
  };
  const view = (y, far) => {
    focus = new THREE.Vector3(0, y, 0);
    distance = far;
  };

  const show = (shelf, item) => {
    clear();
    if (shelf === "textures") {
      const material = Lab.makeMaterial(item, { repeat: 1 });
      const ball = new THREE.Mesh(new THREE.SphereGeometry(0.9, 48, 32), material);
      ball.position.set(-1.1, 1, 0);
      const block = new THREE.Mesh(new THREE.BoxGeometry(1.4, 1.4, 1.4), material);
      block.position.set(1.1, 0.75, 0);
      for (const mesh of [ball, block]) mesh.castShadow = true;
      subject.add(ball, block);
      view(0.9, 4.6);
      return `${item}: ${Lab.TEXTURES[item].about}. Drawn from seeded noise with a colour ramp and a normal map, so it catches the light. makeMaterial("${item}").`;
    }
    if (shelf === "shaders") {
      if (item === "fire" || item === "embers") {
        const fire = Lab.fireMaterial();
        if (item === "fire") {
          for (let i = 0; i < 3; i += 1) {
            const flame = new THREE.Mesh(new THREE.PlaneGeometry(1.4, 2), fire);
            flame.position.y = 1;
            flame.rotation.y = (i * Math.PI) / 3;
            subject.add(flame);
          }
          animated.push(fire);
        }
        const embers = Lab.makeEmbers({ count: item === "fire" ? 80 : 300, area: item === "fire" ? 1.5 : 6, height: 4 });
        subject.add(embers);
        animated.push(embers.material);
        view(1.4, 5);
        return item === "fire" ? "Fire: noise flowing upward inside a flame shape, added on top so it glows. fireMaterial()." : "Embers: points that rise, sway and fade, drawn by a shader. makeEmbers().";
      }
      if (item === "water") {
        const water = new THREE.Mesh(new THREE.PlaneGeometry(8, 8, 64, 64), Lab.waterMaterial());
        water.rotation.x = -Math.PI / 2;
        water.position.y = 0.05;
        subject.add(water);
        animated.push(water.material);
        view(0.2, 6);
        return "Water: waves move the surface, a fresnel sheen at low angles, foam on the crests. waterMaterial().";
      }
      if (item === "glow") {
        const core = new THREE.Mesh(new THREE.SphereGeometry(0.7, 32, 24), new THREE.MeshStandardMaterial({ color: "#1b2a3a", roughness: 0.4 }));
        const shell = new THREE.Mesh(new THREE.SphereGeometry(0.8, 32, 24), Lab.glowMaterial());
        core.position.y = shell.position.y = 1.1;
        subject.add(core, shell);
        animated.push(shell.material);
        view(1.1, 4);
        return "Glow: brightest at the rim, where the surface turns away (fresnel). For magic, auras and a locked-on target. glowMaterial().";
      }
      if (item === "toon") {
        const knot = new THREE.Mesh(new THREE.TorusKnotGeometry(0.6, 0.22, 128, 16), Lab.toonMaterial());
        knot.position.y = 1.1;
        knot.castShadow = true;
        subject.add(knot);
        view(1.1, 4);
        return "Toon: light in three flat bands for a cel-shaded, hand-drawn look. toonMaterial(color).";
      }
      dissolve = Lab.dissolveMaterial();
      const statue = new THREE.Mesh(new THREE.TorusKnotGeometry(0.6, 0.22, 128, 16), dissolve);
      statue.position.y = 1.1;
      subject.add(statue);
      view(1.1, 4);
      return "Dissolve: noise decides which parts burn away first, with a hot edge. For deaths and spells. dissolveMaterial(), uniforms.amount 0 to 1.";
    }
    if (shelf === "models") {
      const makers = {
        warrior: () => Lab.makeWarrior({ color: "#3a2a1c", armour: "#5b4a3a" }).root,
        boss: () => Lab.makeWarrior({ color: "#4a1f16", armour: "#2a2522", weapon: "sword", scale: 2, horns: true }).root,
        tree: () => Lab.makeTree({ height: 4 }),
        "burning tree": () => {
          const tree = Lab.makeTree({ height: 4, burning: true });
          animated.push(tree.userData.fire);
          return tree;
        },
        rock: () => Lab.makeRock({ size: 1, seed: 4 }),
        tower: () => Lab.makeTower({ floors: 4, width: 2.4 }),
        sword: () => {
          const sword = Lab.makeWeapon("sword");
          sword.scale.setScalar(1.6);
          sword.position.y = 0.4;
          return sword;
        },
      };
      subject.add(makers[item]());
      const sizes = { boss: [2.2, 7.5], tree: [2, 7], "burning tree": [2, 7], tower: [4, 13], rock: [0.5, 3.5], sword: [1.4, 3.5] };
      const [y, far] = sizes[item] || [1, 4];
      view(y, far);
      return `${item}: built from shapes in code (lab/kit.js), with its own textures, shadows on every part${item === "warrior" || item === "boss" ? ", and joints for animation" : ""}.`;
    }
    const warrior = Lab.makeWarrior({ color: "#3a2a1c", armour: "#5b4a3a" });
    subject.add(warrior.root);
    pose = (seconds) => {
      const loop = LOOP[item];
      Lab.animateWarrior(warrior, item, loop ? seconds % loop : seconds);
    };
    view(1, 4);
    return `${item}: posed in code every frame (sine waves for loops, eased curves for one-off moves). animateWarrior(warrior, "${item}", seconds).`;
  };

  const clock = new THREE.Clock();
  const loop = () => {
    const seconds = clock.getElapsedTime();
    const width = canvas.clientWidth || 320;
    const height = canvas.clientHeight || 200;
    if (canvas.width !== Math.round(width * renderer.getPixelRatio())) {
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
    }
    const angle = seconds * 0.35;
    camera.position.set(Math.sin(angle) * distance, focus.y + distance * 0.35, Math.cos(angle) * distance);
    camera.lookAt(focus);
    Lab.tick(animated, seconds);
    if (pose) pose(seconds);
    if (dissolve) dissolve.uniforms.amount.value = (Math.sin(seconds * 0.8) * 0.5 + 0.5) * 0.85;
    for (const child of subject.children) if (child.isMesh && child.material.type === "ShaderMaterial" && child.geometry.type === "PlaneGeometry" && child.rotation.x === 0) child.lookAt(camera.position.x, child.position.y, camera.position.z);
    renderer.render(scene, camera);
    frame = requestAnimationFrame(loop);
  };
  frame = requestAnimationFrame(loop);
  canvas.dataset.ready = "true";

  return {
    show,
    textureImage: (kind) => Lab.makeTexture(kind, { size: 256 }).canvas.toDataURL("image/jpeg", 0.85),
    stop: () => {
      cancelAnimationFrame(frame);
      clear();
      renderer.dispose();
      renderer.forceContextLoss();
    },
  };
}
