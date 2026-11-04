// FCCTITLE0: a third-person action game made with the FCC Game Lab kit.
// A warrior on a temple path at dusk faces a horned guardian: dodge-roll
// through its telegraphed blows, strike when it recovers, rest at the
// bonfire. Everything is drawn in code: no outside art.
import * as THREE from "three";
import * as Lab from "./lab/kit.js";

// ------------------------------------------------------------- tuning
const TUNE = {
  player: { hp: 100, stamina: 100, speed: 4.2, rollSpeed: 9, rollCost: 25, attackCost: 18, heavyCost: 32, regen: 28, flasks: 3, heal: 45 },
  boss: { name: "Ashen Guardian", hp: 420, speed: 2.1, reach: 2.8, damage: 26, slam: 38 },
  arena: 22,
};

// ------------------------------------------------------------- the scene
const canvas = document.querySelector("#game");
const renderer = Lab.makeRenderer(canvas);
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(60, 1, 0.1, 500);
Lab.addLights(scene);
scene.add(Lab.makeSky());

const ground = new THREE.Mesh(new THREE.CircleGeometry(TUNE.arena + 18, 64), Lab.makeMaterial("grass", { repeat: 18 }));
ground.rotation.x = -Math.PI / 2;
ground.receiveShadow = true;
scene.add(ground);
const path = new THREE.Mesh(new THREE.PlaneGeometry(6, TUNE.arena * 2.4), Lab.makeMaterial("stone", { repeat: 6 }));
path.rotation.x = -Math.PI / 2;
path.position.y = 0.01;
path.receiveShadow = true;
scene.add(path);

const tower = Lab.makeTower({ floors: 6 });
tower.position.set(0, 0, -TUNE.arena - 6);
scene.add(tower);

const animated = [];
const flames = [];
for (let i = 0; i < 14; i += 1) {
  const side = i % 2 ? 1 : -1;
  const tree = Lab.makeTree({ seed: i + 3, height: 5 + (i % 3), burning: i % 3 !== 0 });
  tree.position.set(side * (6 + (i % 4) * 2.2), 0, -TUNE.arena + i * 3.4);
  scene.add(tree);
  if (tree.userData.fire) {
    animated.push(tree.userData.fire);
    tree.traverse((child) => child.userData.flame && flames.push(child));
  }
}
for (let i = 0; i < 10; i += 1) {
  const rock = Lab.makeRock({ seed: i + 20, size: 0.5 + (i % 3) * 0.4 });
  rock.position.set((i % 2 ? 1 : -1) * (4 + (i % 5)), 0.2, -TUNE.arena + i * 4.5);
  scene.add(rock);
}
const embers = Lab.makeEmbers({ count: 260, area: 26, height: 8 });
scene.add(embers);
animated.push(embers.material);

// The bonfire: where you rest and come back.
const bonfire = new THREE.Group();
const fireMat = Lab.fireMaterial();
animated.push(fireMat);
for (let i = 0; i < 3; i += 1) {
  const flame = new THREE.Mesh(new THREE.PlaneGeometry(1, 1.4), fireMat);
  flame.position.y = 0.7;
  flame.rotation.y = (i * Math.PI) / 3;
  bonfire.add(flame);
}
const logs = new THREE.Mesh(new THREE.CylinderGeometry(0.5, 0.6, 0.18, 10), new THREE.MeshStandardMaterial({ color: "#2b1a10" }));
bonfire.add(logs);
const bonfireLight = new THREE.PointLight("#ff8a3a", 6, 10, 1.6);
bonfireLight.position.y = 1.2;
bonfire.add(bonfireLight);
bonfire.position.set(0, 0, TUNE.arena - 2);
scene.add(bonfire);
const bonfireEmbers = Lab.makeEmbers({ count: 60, area: 1.2, height: 3, seed: 9 });
bonfireEmbers.position.copy(bonfire.position);
scene.add(bonfireEmbers);
animated.push(bonfireEmbers.material);

// ------------------------------------------------------------- the fighters
const player = Lab.makeWarrior({ color: "#3a2a1c", armour: "#5b4a3a", weapon: "staff" });
player.root.position.set(0, 0, TUNE.arena - 5);
scene.add(player.root);
const boss = Lab.makeWarrior({ color: "#4a1f16", armour: "#2a2522", weapon: "sword", scale: 2.4, horns: true });
const aura = new THREE.Mesh(new THREE.SphereGeometry(0.75, 20, 16), Lab.glowMaterial({ color: "#ff5a2a", strength: 0 }));
aura.position.y = 1.4;
boss.root.add(aura);
animated.push(aura.material);
scene.add(boss.root);
const warn = new THREE.Mesh(new THREE.RingGeometry(0.2, TUNE.boss.reach + 0.6, 40), new THREE.MeshBasicMaterial({ color: "#ff3b2a", transparent: true, opacity: 0, side: THREE.DoubleSide, depthWrite: false }));
warn.rotation.x = -Math.PI / 2;
warn.position.y = 0.03;
scene.add(warn);

const hud = {
  hp: document.querySelector("#hp i"),
  stamina: document.querySelector("#stamina i"),
  flasks: document.querySelector("#flasks"),
  bossBar: document.querySelector("#boss"),
  bossHp: document.querySelector("#boss i"),
  banner: document.querySelector("#banner"),
  hint: document.querySelector("#hint"),
};
const input = Lab.makeControls(document.querySelector("#stage"));

// ------------------------------------------------------------- state
const me = { hp: 0, stamina: 0, flasks: 0, state: "idle", t: 0, facing: Math.PI, hitBy: -1, alive: true };
const foe = { hp: 0, state: "idle", t: 0, facing: 0, swing: 0, phase: 1, alive: true, awake: false };
let locked = false;
let yaw = Math.PI;
let bannerTime = 0;

function reset() {
  Object.assign(me, { hp: TUNE.player.hp, stamina: TUNE.player.stamina, flasks: TUNE.player.flasks, state: "idle", t: 0, alive: true });
  Object.assign(foe, { hp: TUNE.boss.hp, state: "idle", t: 0, phase: 1, alive: true, awake: false });
  player.root.position.set(0, 0, TUNE.arena - 5);
  boss.root.position.set(0, 0, -TUNE.arena + 6);
  boss.root.visible = true;
  aura.material.uniforms.strength.value = 0;
  locked = false;
  hud.bossBar.hidden = true;
}

function banner(text, tone) {
  hud.banner.textContent = text;
  hud.banner.className = tone;
  hud.banner.hidden = false;
  bannerTime = 3;
}

const flat = (v) => new THREE.Vector3(v.x, 0, v.z);
const angleTo = (from, to) => Math.atan2(to.x - from.x, to.z - from.z);
const turnTowards = (current, target, rate) => current + Math.atan2(Math.sin(target - current), Math.cos(target - current)) * Math.min(1, rate);

function start(action) {
  me.state = action;
  me.t = 0;
  me.hitBy = -1;
}

// ------------------------------------------------------------- the loop
function updatePlayer(dt) {
  me.t += dt;
  const busy = ["attack", "heavy", "roll", "hit", "dead"].includes(me.state);
  if (!busy) me.stamina = Math.min(TUNE.player.stamina, me.stamina + TUNE.player.regen * dt);
  if (!me.alive) return;
  if (input.take("lock")) locked = !locked && foe.alive && foe.awake;
  if (!busy) {
    if (input.take("roll") && me.stamina >= TUNE.player.rollCost) {
      me.stamina -= TUNE.player.rollCost;
      start("roll");
    } else if (input.take("attack") && me.stamina >= TUNE.player.attackCost) {
      me.stamina -= TUNE.player.attackCost;
      start("attack");
    } else if (input.take("heavy") && me.stamina >= TUNE.player.heavyCost) {
      me.stamina -= TUNE.player.heavyCost;
      start("heavy");
    } else if (input.take("heal") && me.flasks > 0 && me.hp < TUNE.player.hp) {
      me.flasks -= 1;
      me.hp = Math.min(TUNE.player.hp, me.hp + TUNE.player.heal);
    }
  }
  // Move relative to the camera.
  yaw += input.look;
  input.look = 0;
  const forward = new THREE.Vector3(Math.sin(yaw), 0, Math.cos(yaw));
  const right = new THREE.Vector3(-forward.z, 0, forward.x);
  const wish = forward.multiplyScalar(-input.y).add(right.multiplyScalar(input.x));
  const moving = wish.lengthSq() > 0.02;
  if (me.state === "roll") {
    const dir = new THREE.Vector3(Math.sin(me.facing), 0, Math.cos(me.facing));
    player.root.position.addScaledVector(dir, TUNE.player.rollSpeed * dt * (1 - me.t / 0.55));
    if (me.t >= 0.55) me.state = "idle";
  } else if (!busy) {
    if (moving) {
      wish.normalize();
      me.facing = turnTowards(me.facing, Math.atan2(wish.x, wish.z), dt * 12);
      player.root.position.addScaledVector(wish, TUNE.player.speed * dt);
      me.state = "walk";
    } else {
      me.state = "idle";
    }
  }
  if (locked && foe.alive && me.state !== "roll") me.facing = turnTowards(me.facing, angleTo(player.root.position, boss.root.position), dt * 10);
  // Attacks land in the middle of the swing.
  if (me.state === "attack" || me.state === "heavy") {
    const length = me.state === "heavy" ? 1.1 : 0.55;
    const p = me.t / length;
    const toFoe = flat(boss.root.position).sub(flat(player.root.position));
    const facing = Math.abs(Math.atan2(Math.sin(angleTo(player.root.position, boss.root.position) - me.facing), Math.cos(angleTo(player.root.position, boss.root.position) - me.facing)));
    if (p > 0.45 && p < 0.7 && me.hitBy !== 1 && foe.alive && toFoe.length() < 2.6 && facing < 1.0) {
      me.hitBy = 1;
      foe.hp -= me.state === "heavy" ? 48 : 22;
      foe.awake = true;
      if (foe.hp <= 0) {
        foe.alive = false;
        foe.state = "dead";
        foe.t = 0;
        locked = false;
        banner("GUARDIAN FELLED", "win");
      }
    }
    if (p >= 1) me.state = "idle";
  }
  if (me.state === "hit" && me.t > 0.35) me.state = "idle";
  // Stay in the arena.
  const where = flat(player.root.position);
  if (where.length() > TUNE.arena + 4) player.root.position.copy(where.setLength(TUNE.arena + 4));
  player.root.rotation.y = me.facing;
  // Rest at the bonfire: full health and flasks.
  const near = player.root.position.distanceTo(bonfire.position) < 2.2;
  hud.hint.hidden = !near;
  if (near && input.take("heal") && me.state === "idle") {
    me.hp = TUNE.player.hp;
    me.flasks = TUNE.player.flasks;
  }
}

function hurt(amount) {
  if (!me.alive || (me.state === "roll" && me.t > 0.05 && me.t < 0.4)) return; // a roll's i-frames
  me.hp -= amount;
  if (me.hp <= 0) {
    me.alive = false;
    me.state = "dead";
    me.t = 0;
    banner("YOU DIED", "dead");
    setTimeout(reset, 3200);
  } else {
    start("hit");
  }
}

function updateBoss(dt) {
  foe.t += dt;
  if (!foe.alive) {
    if (foe.t > 2.5) boss.root.visible = false;
    return;
  }
  const toMe = flat(player.root.position).sub(flat(boss.root.position));
  const distance = toMe.length();
  if (!foe.awake && distance < 14) foe.awake = true;
  hud.bossBar.hidden = !foe.awake;
  if (!foe.awake || !me.alive) {
    foe.state = "idle";
    return;
  }
  if (foe.phase === 1 && foe.hp < TUNE.boss.hp / 2) {
    foe.phase = 2;
    aura.material.uniforms.strength.value = 1.6;
  }
  const speed = TUNE.boss.speed * (foe.phase === 2 ? 1.35 : 1);
  const faceMe = () => (foe.facing = turnTowards(foe.facing, Math.atan2(toMe.x, toMe.z), dt * 4));
  switch (foe.state) {
    case "idle":
    case "walk":
      faceMe();
      if (distance > TUNE.boss.reach) {
        boss.root.position.addScaledVector(toMe.normalize(), speed * dt);
        foe.state = "walk";
      } else {
        foe.state = Math.random() < (foe.phase === 2 ? 0.45 : 0.3) ? "slam" : "windup";
        foe.t = 0;
      }
      break;
    case "windup":
    case "slam": {
      const heavy = foe.state === "slam";
      const windup = (heavy ? 1.1 : 0.7) / (foe.phase === 2 ? 1.25 : 1);
      if (foe.t < windup) faceMe();
      warn.position.set(boss.root.position.x, 0.03, boss.root.position.z);
      warn.material.opacity = foe.t < windup ? 0.15 + 0.5 * (foe.t / windup) : 0;
      if (foe.t >= windup && foe.swing === 0) {
        foe.swing = 1;
        const ahead = Math.abs(Math.atan2(Math.sin(Math.atan2(toMe.x, toMe.z) - foe.facing), Math.cos(Math.atan2(toMe.x, toMe.z) - foe.facing)));
        if (distance < TUNE.boss.reach + (heavy ? 0.8 : 0.3) && (heavy || ahead < 1.2)) hurt(heavy ? TUNE.boss.slam : TUNE.boss.damage);
      }
      if (foe.t >= windup + 0.9) {
        foe.state = "recover";
        foe.t = 0;
        foe.swing = 0;
      }
      break;
    }
    case "recover":
      warn.material.opacity = 0;
      if (foe.t > (foe.phase === 2 ? 0.6 : 1.0)) foe.state = "idle";
      break;
    default:
      foe.state = "idle";
  }
  boss.root.rotation.y = foe.facing;
}

function pose(clock) {
  const playerTime = ["idle", "walk"].includes(me.state) ? clock : me.t;
  Lab.animateWarrior(player, me.state === "walk" ? "run" : me.state, playerTime);
  const bossState = { idle: "idle", walk: "walk", windup: "attack", slam: "heavy", recover: "idle", dead: "dead" }[foe.state] || "idle";
  const windupLength = foe.state === "slam" ? 1.1 : 0.7;
  Lab.animateWarrior(boss, bossState, ["idle", "walk"].includes(bossState) ? clock : bossState === "dead" ? foe.t : (foe.t / (windupLength + 0.3)) * (bossState === "heavy" ? 1.1 : 0.55));
}

function updateCamera(dt) {
  const target = player.root.position.clone().add(new THREE.Vector3(0, 1.6, 0));
  if (locked && foe.alive) yaw = turnTowards(yaw, angleTo(boss.root.position, player.root.position), dt * 6);
  const behind = new THREE.Vector3(Math.sin(yaw), 0, Math.cos(yaw)).multiplyScalar(5.2);
  const wanted = target.clone().add(behind).add(new THREE.Vector3(0, 1.8, 0));
  camera.position.lerp(wanted, Math.min(1, dt * 6));
  camera.lookAt(locked && foe.alive ? boss.root.position.clone().add(new THREE.Vector3(0, 2, 0)).lerp(target, 0.5) : target);
}

function updateHud() {
  hud.hp.style.width = `${Math.max(0, (me.hp / TUNE.player.hp) * 100)}%`;
  hud.stamina.style.width = `${Math.max(0, (me.stamina / TUNE.player.stamina) * 100)}%`;
  hud.flasks.textContent = `✚ ${me.flasks}`;
  hud.bossHp.style.width = `${Math.max(0, (foe.hp / TUNE.boss.hp) * 100)}%`;
}

function resize() {
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  renderer.setSize(width, height, false);
  camera.aspect = width / height;
  camera.updateProjectionMatrix();
}
window.addEventListener("resize", resize);

const clock = new THREE.Clock();
function frame() {
  const dt = Math.min(clock.getDelta(), 0.05);
  const now = clock.elapsedTime;
  updatePlayer(dt);
  updateBoss(dt);
  pose(now);
  updateCamera(dt);
  updateHud();
  Lab.tick(animated, now);
  for (const flame of flames) flame.lookAt(camera.position.x, flame.getWorldPosition(new THREE.Vector3()).y, camera.position.z);
  bonfire.children.forEach((child, i) => i < 3 && child.lookAt(camera.position.x, 0.7, camera.position.z));
  bonfireLight.intensity = 5 + Math.sin(now * 11) * 0.6 + Math.sin(now * 5.3) * 0.5;
  if (bannerTime > 0 && (bannerTime -= dt) <= 0) hud.banner.hidden = true;
  renderer.render(scene, camera);
  requestAnimationFrame(frame);
}

reset();
resize();
camera.position.set(0, 4, TUNE.arena + 2);
document.documentElement.dataset.ready = "true";
requestAnimationFrame(frame);
