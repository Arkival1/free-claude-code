// Boots the game: load or make a world, run the loop, save often.
import { Sim } from "./sim.js";
import { Renderer } from "./render.js";
import { UI } from "./ui.js";
import { AiVoices } from "./ai.js";
import { store } from "./store.js";

const SAVE_KEY = "hearthbox.save.v1";
const MIN_PER_SEC = 4; // game minutes per real second at normal speed

const game = {
  sim: null,
  speed: 1,
  r: new Renderer(document.getElementById("world")),
  ai: new AiVoices(),
  ui: null,
  setSim(sim) {
    this.sim = sim;
    this.r.setSim(sim);
    this.ai.attach(sim);
    if (this.ui) {
      sim.onEvent = (e) => this.ui.toast(e);
      this.ui.sel = null;
      this.ui.selBuilding = null;
      this.ui.closeSheet();
      this.ui.setTool(null);
    }
    const v = sim.villages[0];
    const h = v && sim.hallOf(v);
    if (h) this.r.center(h.x + 1.5, h.y + 2.5);
  },
  newWorld(seed) {
    this.setSim(Sim.create(seed));
    this.save();
  },
  save() {
    return store.set(SAVE_KEY, JSON.stringify(this.sim.serialize()));
  },
  load() {
    const raw = store.get(SAVE_KEY);
    if (!raw) return null;
    try {
      return Sim.deserialize(JSON.parse(raw));
    } catch (e) {
      console.warn("Save was unreadable, starting fresh", e);
      return null;
    }
  },
};
window.hearthbox = game;

function boot() {
  const params = new URLSearchParams(location.search);
  const fresh = params.has("new") || params.has("seed");
  const sim = (!fresh && game.load()) || Sim.create(params.has("seed") ? +params.get("seed") : undefined);
  game.r.resize();
  game.r.cam.z = Math.max(12 * game.r.dpr, Math.min(40 * game.r.dpr, game.r.c.width / 15));
  game.setSim(sim);
  game.ui = new UI(game);
  game.ui.init();
  window.addEventListener("resize", () => game.r.resize());
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) game.save();
  });
  window.addEventListener("pagehide", () => game.save());
  setInterval(() => game.save(), 30000);
  let last = performance.now();
  const frame = (now) => {
    const dt = Math.min(0.1, (now - last) / 1000);
    last = now;
    if (game.speed > 0) {
      try {
        game.sim.advance(dt * game.speed * MIN_PER_SEC);
      } catch (e) {
        console.error(e);
        game.speed = 0;
      }
    }
    const ui = game.ui;
    game.r.draw({ sel: ui.sel, selBuilding: ui.selBuilding, ghost: ui.ghost, brush: ui.tool && ui.tool.kind === "land" ? ui.brush : null, names: ui.opts.names, bubbles: ui.opts.bubbles });
    ui.tick(now);
    requestAnimationFrame(frame);
  };
  requestAnimationFrame(frame);
}
boot();
