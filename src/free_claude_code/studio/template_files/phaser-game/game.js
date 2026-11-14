// A Phaser 3 platformer built from Kenney's free art and sound (CC0).
// Change LEVEL to draw a new level; swap the sheets in assets/ (the
// game_assets tool finds more) and the frame numbers below to restyle it.
(() => {
  "use strict";
  const TILE = 18;
  const FRAMES = {
    ground: 2, dirt: 122, coin: [151, 152], spikes: 68, flag: [111, 112],
    hero: [0, 1], crawler: [18, 19, 20],
  };
  // # ground   o coin   ^ spikes   e crawler   P player start   F flag
  const LEVEL = [
    "                                                                         ",
    "                                                                         ",
    "                                  ooo                                    ",
    "                                 #####              ooo                  ",
    "                    ooo                            #####          F      ",
    "                   #####       e                                  #      ",
    "         o o                 #####                                #      ",
    "        #####                          ooo      e                 #      ",
    "   P                    e             #####   #####       ^^^^    #      ",
    "##########  ##################   #######################  ###############",
    "##########  ##################   #######################  ###############",
  ];
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const $ = (id) => document.getElementById(id);
  const hud = (text) => { $("hud").textContent = text; };
  const say = (text) => { $("msg").textContent = text; };

  // Held touch buttons, merged with the keyboard each frame.
  const held = new Set();
  for (const button of document.querySelectorAll("[data-key]")) {
    const key = button.dataset.key;
    const on = (e) => { e.preventDefault(); held.add(key); button.classList.add("down"); };
    const off = (e) => { e.preventDefault(); held.delete(key); button.classList.remove("down"); };
    button.addEventListener("pointerdown", on);
    for (const type of ["pointerup", "pointerleave", "pointercancel"]) button.addEventListener(type, off);
  }

  class Level extends Phaser.Scene {
    constructor() { super("level"); }

    preload() {
      this.load.spritesheet("tiles", "assets/tiles.png", { frameWidth: TILE, frameHeight: TILE });
      this.load.spritesheet("chars", "assets/characters.png", { frameWidth: 24, frameHeight: 24 });
      for (const name of ["glass", "punch", "error", "step", "jingle_win"]) {
        this.load.audio(name, `assets/sounds/${name}.mp3`);
      }
    }

    create() {
      const width = LEVEL[0].length * TILE, height = LEVEL.length * TILE;
      this.cameras.main.setBackgroundColor("#79c7e3");
      this.physics.world.setBounds(0, 0, width, height + 60);
      this.solid = this.physics.add.staticGroup();
      this.coins = this.physics.add.staticGroup();
      this.spikes = this.physics.add.staticGroup();
      this.crawlers = this.physics.add.group();
      // Clouds on a slow parallax layer give depth.
      for (let i = 0; i < 12; i++) {
        this.add.circle(i * 130 + 40, 30 + (i % 3) * 18, 14 + (i % 4) * 4, 0xffffff, 0.75).setScrollFactor(0.3);
      }
      this.anims.create({ key: "walk", frames: this.anims.generateFrameNumbers("chars", { frames: FRAMES.hero }), frameRate: 8, repeat: -1 });
      this.anims.create({ key: "spin", frames: this.anims.generateFrameNumbers("tiles", { frames: FRAMES.coin }), frameRate: 6, repeat: -1 });
      this.anims.create({ key: "crawl", frames: this.anims.generateFrameNumbers("chars", { frames: FRAMES.crawler }), frameRate: 6, repeat: -1 });
      this.anims.create({ key: "wave", frames: this.anims.generateFrameNumbers("tiles", { frames: FRAMES.flag }), frameRate: 4, repeat: -1 });
      LEVEL.forEach((row, y) => [...row].forEach((cell, x) => {
        const px = x * TILE + TILE / 2, py = y * TILE + TILE / 2;
        if (cell === "#") this.solid.create(px, py, "tiles", y === 0 || LEVEL[y - 1][x] !== "#" ? FRAMES.ground : FRAMES.dirt);
        else if (cell === "o") this.coins.create(px, py, "tiles", FRAMES.coin[0]).play("spin");
        else if (cell === "^") this.spikes.create(px, py + 4, "tiles", FRAMES.spikes).setSize(16, 8).setOffset(1, 10);
        else if (cell === "e") this.crawlers.create(px, py, "chars", FRAMES.crawler[0]).setVelocityX(-40).setBounceX(1).setCollideWorldBounds(true).play("crawl");
        else if (cell === "P") this.start = { x: px, y: py };
        else if (cell === "F") this.flag = this.physics.add.staticSprite(px, py + 4, "tiles", FRAMES.flag[0]).play("wave");
      }));
      this.player = this.physics.add.sprite(this.start.x, this.start.y, "chars", FRAMES.hero[0]).setSize(16, 20).setOffset(4, 4);
      this.player.setCollideWorldBounds(true);
      this.physics.add.collider(this.player, this.solid);
      this.physics.add.collider(this.crawlers, this.solid);
      this.physics.add.overlap(this.player, this.coins, (_, coin) => this.collect(coin));
      this.physics.add.overlap(this.player, this.crawlers, (player, crawler) => this.touch(player, crawler));
      this.physics.add.overlap(this.player, this.spikes, () => this.hurt());
      this.physics.add.overlap(this.player, this.flag, () => this.win());
      this.cameras.main.startFollow(this.player, true, 0.12, 0.12).setBounds(0, 0, width, height).setZoom(2);
      this.burst = this.add.particles(0, 0, "tiles", { frame: FRAMES.coin[0], speed: { min: 30, max: 90 }, scale: { start: 0.5, end: 0 }, lifespan: 400, emitting: false });
      this.keys = this.input.keyboard.addKeys("LEFT,RIGHT,UP,SPACE,A,D,W");
      Object.assign(this, { score: 0, lives: 3, coyote: 0, buffer: 0, done: false, hurtUntil: 0, jumpWas: false });
      this.paint(); say("");
    }

    paint() { hud(`Coins ${this.score}   ${"♥".repeat(Math.max(0, this.lives))}`); }

    collect(coin) {
      this.burst.explode(8, coin.x, coin.y);
      coin.destroy(); this.score += 1; this.paint(); this.sound.play("glass", { volume: 0.5 });
    }

    touch(player, crawler) {
      if (player.body.velocity.y > 40 && player.y < crawler.y - 6) {
        // Stomp: squash the crawler and bounce.
        crawler.disableBody(true, false);
        this.tweens.add({ targets: crawler, scaleY: 0.2, alpha: 0, duration: 220, onComplete: () => crawler.destroy() });
        player.setVelocityY(-260); this.sound.play("punch", { volume: 0.6 });
        if (!reduce) this.cameras.main.shake(90, 0.004);
      } else this.hurt();
    }

    hurt() {
      if (this.time.now < this.hurtUntil || this.done) return;
      this.lives -= 1; this.paint(); this.hurtUntil = this.time.now + 1200;
      this.sound.play("error", { volume: 0.6 });
      this.player.setVelocity(-140 * Math.sign(this.player.body.velocity.x || 1), -200);
      this.tweens.add({ targets: this.player, alpha: 0.3, yoyo: true, repeat: 5, duration: 100 });
      if (this.lives <= 0) this.end("Out of lives. Press Play to try again.");
    }

    win() {
      if (this.done) return;
      this.sound.play("jingle_win", { volume: 0.6 });
      this.end(`Level done with ${this.score} coins!`);
    }

    end(message) {
      this.done = true; this.physics.pause(); say(message);
      $("cover").hidden = false; $("play").textContent = "Play again";
    }

    update(_, dt) {
      if (this.done) return;
      const p = this.player, k = this.keys, onGround = p.body.blocked.down;
      const left = k.LEFT.isDown || k.A.isDown || held.has("left");
      const right = k.RIGHT.isDown || k.D.isDown || held.has("right");
      const jump = k.UP.isDown || k.SPACE.isDown || k.W.isDown || held.has("jump");
      // Acceleration, coyote time and a jump buffer make the controls forgiving.
      p.setVelocityX(Phaser.Math.Linear(p.body.velocity.x, (right - left) * 150, onGround ? 0.25 : 0.12));
      this.coyote = onGround ? 100 : this.coyote - dt;
      this.buffer = jump && !this.jumpWas ? 120 : this.buffer - dt;
      if (this.buffer > 0 && this.coyote > 0) {
        p.setVelocityY(-330); this.buffer = 0; this.coyote = 0; this.sound.play("step", { volume: 0.5 });
      }
      if (!jump && p.body.velocity.y < -120) p.setVelocityY(p.body.velocity.y * 0.85); // short hop
      this.jumpWas = jump;
      if (Math.abs(p.body.velocity.x) > 10) { p.setFlipX(p.body.velocity.x > 0); if (onGround) p.play("walk", true); }
      else if (onGround) { p.anims.stop(); p.setFrame(FRAMES.hero[0]); }
      if (!onGround) p.setFrame(FRAMES.hero[1]);
      for (const crawler of this.crawlers.getChildren()) if (crawler.body) crawler.setFlipX(crawler.body.velocity.x > 0);
      if (p.y > this.physics.world.bounds.height - 40) {
        this.hurt();
        if (!this.done) p.setPosition(this.start.x, this.start.y);
      }
    }
  }

  let game = null;
  $("play").addEventListener("click", () => {
    $("cover").hidden = true;
    if (game) { game.scene.getScene("level").scene.restart(); return; }
    game = new Phaser.Game({
      type: Phaser.AUTO,
      parent: "screen",
      width: 480,
      height: 270,
      pixelArt: true,
      backgroundColor: "#000000",
      physics: { default: "arcade", arcade: { gravity: { y: 900 } } },
      scale: { mode: Phaser.Scale.FIT, autoCenter: Phaser.Scale.CENTER_BOTH },
      scene: Level,
    });
    window.game = game; // handy in the browser console and for tests
  });
  // Pause when the tab is hidden.
  document.addEventListener("visibilitychange", () => {
    if (!game) return;
    if (document.hidden) game.loop.sleep(); else game.loop.wake();
  });
})();
