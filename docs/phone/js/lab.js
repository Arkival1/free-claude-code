// The Game Lab on the phone: the kit (lab/kit.js: textures, shaders, models
// and animation made in code, on three.js) and a third-person action starter
// (lab/souls/) that 3D games grow from. The lab tool lets the AI read the
// guide, see what the kit has, and put the kit in a project.

/** The 3D starter's files, from the app's own copies, named for the project. */
const STARTER = { "index.html": "lab/souls/index.html", "styles.css": "lab/souls/styles.css", "game.js": "lab/souls/game.js", "lab/kit.js": "lab/kit.js" };

async function appFile(path) {
  const response = await fetch(new URL(`../${path}`, import.meta.url));
  if (!response.ok) throw new Error(`The Lab couldn't read ${path} (${response.status}).`);
  return response.text();
}

/** The game3d template: a third-person action game on the Lab kit. */
export async function game3dFiles(title) {
  const clean = String(title || "3D game").replace(/[<>]/g, "");
  const files = {};
  for (const [path, from] of Object.entries(STARTER)) files[path] = (await appFile(from)).replaceAll("FCCTITLE0", clean);
  return files;
}

export const GAME3D_ABOUT =
  "game3d: a third-person 3D action game (Souls-like): a warrior with a stamina bar, dodge roll with i-frames, light and heavy attacks, lock-on, healing flasks, a horned boss with telegraphed blows and a second phase, a bonfire checkpoint, burning trees, a tower, embers and fog at dusk, touch controls. Built on the Lab kit (lab/kit.js).";

/** What the kit has (the same as KIT in lab/kit.js). */
export const KIT_PARTS = {
  textures: "makeTexture(kind, {size, seed, repeat}) and makeMaterial(kind): stone, wood, grass, metal, lava (glowing cracks), sand, bark, ice; colour, normal map and roughness drawn from seeded noise",
  shaders: "fireMaterial() flames, makeEmbers({count, area, height}) rising sparks, waterMaterial() waves and sheen, glowMaterial({color}) rim glow, toonMaterial(color) cel shading, dissolveMaterial() burn away (uniforms.amount), makeSky({top, horizon, sun}); call tick(materials, seconds) each frame",
  models: "makeWarrior({color, armour, weapon, scale, horns}) jointed fighter, makeTree({height, bare, burning}), makeRock({seed, size}), makeTower({floors}) pagoda, makeWeapon('sword' | 'staff')",
  animation: "animateWarrior(warrior, state, seconds): idle, walk, run, attack, heavy, roll, hit, dead (procedural poses with easing; returns progress 0..1)",
  stage: "makeRenderer(canvas) phone-tuned, addLights(scene) dusk light, shadows and fog, makeControls(root) joystick and buttons (keys on a computer)",
  noise: "seeded(seed), valueNoise(seed, period), fbm(seed, octaves, period): for your own textures, terrain and patterns",
};

/** How to engineer a 3D game that looks good and plays well on a phone. */
export const LAB_GUIDE = `3D game engineering with the FCC Game Lab (three.js r186)

Start: start_project with template game3d (a third-person action game on the kit), then make it the user's: the world, the enemies, the boss, the story, the colours. game.js imports * as THREE from "three" and * as Lab from "./lab/kit.js"; both already work in the preview.

Look (what makes a phone game look expensive):
- Light: one low warm sun with shadows (shadow map 1024), a hemisphere sky light, and fog (FogExp2) in a colour between the sky and the ground. Dusk and night read best.
- Tone mapping ACES, sRGB textures, a gradient sky (makeSky). Fewer, bigger shapes beat many small ones.
- Materials: MeshStandardMaterial with a colour map, a normal map and roughness (makeMaterial). Metal is low roughness and high metalness; stone and bark are rough.
- Atmosphere: embers, fire, glow and dissolve shaders, a pulsing point light near fire, slow camera smoothing.

Make your own, in the kit's style (original, never copied):
- Texture: noise → height (fbm, cells, grain) → colour ramp (dark, mid, light) → normal map from the height (Sobel). Seed it so it's the same every time.
- Shader: a ShaderMaterial with uniforms {time, colour}; vertex shader passes uv/normal; fragment shader uses noise(), fbm(), smoothstep and fresnel (pow(1 - dot(N, V), p)). Additive blending and depthWrite false for fire, glow and particles.
- Model: build from boxes, capsules, cones, cylinders and dodecahedrons in a Group; jitter vertices with a seeded random for rocks; put limbs on pivot Groups at the joint so they rotate naturally; castShadow on every mesh.
- Animation: pose pivots with Math.sin for loops (walk, breathe) and eased curves for one-offs (attack: wind up, strike, recover). Keep each action's length in one place so hit timing matches.

Souls-like design (what makes it feel right):
- Stamina for every roll and swing; it refills only when you stop acting.
- Every enemy attack is telegraphed: a wind-up pose, a glow or a ring on the ground, then the blow, then a recovery window to punish.
- Dodge roll with i-frames in the middle of the roll; a lock-on that turns the camera and the player to the target.
- Checkpoints (a bonfire) that refill health and flasks; death sends you back with the boss reset; a boss with a second phase (faster, new move) at half health.
- A readable arena: a clear path, landmarks (a tower), light where the danger is.

The user's art direction (from the game shots they shared; make your own originals in this spirit, never copies of those games or their characters):
- Ember temple at dusk: a stone path between burning trees, a tiered pagoda tower on the horizon, orange-red fog, embers drifting up, a lone warrior with a long staff seen from behind. Warm orange against cold blue-black shadow.
- Misty cliffs: a staff-wielding hero in layered armour on a rock above white mist, a pale dragon shape in the clouds, green moss on grey stone, soft back light.
- Bright fantasy: saturated mushrooms, glowing plants and crystal stones on a grid, a party of heroes, a tactics menu; or a cosy cartoon fox in warm lantern light.
- Painterly open world: rolling grass, orange shrubs, dark pine clusters, purple rocky peaks, a rider on a path; flat painted shapes with soft light (toon materials and fog).
- Gritty action: soldiers with banners and rifles against giant bugs at night under blue light; a desert road with a huge creature; a hand casting a glowing rune circle at a demon (glow and fire shaders, strong rim light).
- Characters read by silhouette: big shoulders and a weapon for warriors, horns and size for bosses, a clear colour for each faction; armour layers in two or three materials (metal, cloth, leather).

Phones: cap the pixel ratio at about 1.6, keep shadows to one light, reuse materials and geometry, keep particles under a few hundred, and test with look_at_site. Touch controls first (makeControls); keys work too.

Bigger games: split game.js into modules (player.js, boss.js, world.js) that import from "three" and "./lab/kit.js"; the preview follows imports between your files.`;

/** The lab tool: the guide, what the kit has, or put the kit in the project. */
export async function useLab(args, ctx, writeFile) {
  const action = String(args.action || "guide");
  if (action === "guide") return LAB_GUIDE;
  if (action === "list") return `The Lab kit (lab/kit.js; import * as Lab from "./lab/kit.js"):\n${Object.entries(KIT_PARTS).map(([part, about]) => `- ${part}: ${about}`).join("\n")}\n\nThe game3d template: ${GAME3D_ABOUT}`;
  if (action === "add") {
    if (!ctx.project) throw new Error("Start or pick a project first (start_project).");
    const text = await appFile("lab/kit.js");
    await writeFile(ctx.project, "lab/kit.js", text);
    return `Put the Lab kit in ${ctx.project.name} as lab/kit.js. Import it from a module script: import * as THREE from "three"; import * as Lab from "./lab/kit.js";`;
  }
  throw new Error("action is guide, list or add.");
}
