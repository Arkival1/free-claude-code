// The gold AI core from the PC HUD, drawn the same way on the phone.

export const ORB_STATES = {
  idle: { spin: 0.14, swirl: 0.0, heat: 0.75, spread: 0.02, streak: 0.25 },
  thinking: { spin: 0.55, swirl: 0.9, heat: 1.0, spread: 0.04, streak: 0.8 },
  listening: { spin: 0.2, swirl: 0.15, heat: 0.95, spread: 0.1, streak: 0.35 },
  hearing: { spin: 0.4, swirl: 0.5, heat: 1.05, spread: 0.06, streak: 0.6 },
  speaking: { spin: 0.28, swirl: 0.25, heat: 1.1, spread: 0.12, streak: 0.55 },
  offline: { spin: 0.04, swirl: 0.0, heat: 0.3, spread: 0.0, streak: 0.05 },
};

export function createCoreOrb(canvas) {
  const ctx = canvas.getContext("2d");
  const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const small = Math.min(window.innerWidth, window.innerHeight) < 700;
  // Fewer particles and 30 frames a second on phones and older PCs keep
  // the core smooth and leave the processor for the AI.
  const modest = small || (navigator.hardwareConcurrency || 4) <= 4;
  const frameGap = modest ? 1000 / 30 : 0;
  let lastFrame = 0;
  const count = small ? 900 : modest ? 1400 : 2200;
  const golden = Math.PI * (3 - Math.sqrt(5));
  const points = Array.from({ length: count }, (_, i) => {
    const y = 1 - (i / (count - 1)) * 2;
    const r = Math.sqrt(1 - y * y);
    const theta = golden * i;
    const shell = Math.random() < 0.22 ? 0.25 + Math.random() * 0.6 : 0.86 + Math.random() * 0.18;
    return {
      x: Math.cos(theta) * r,
      y,
      z: Math.sin(theta) * r,
      shell,
      size: 0.6 + Math.random() * 1.5,
      phase: Math.random() * Math.PI * 2,
      streak: Math.random() < 0.22,
    };
  });
  const rings = [0.35, -0.6, 1.1].map((tilt, index) => ({
    tilt,
    speed: 0.25 + index * 0.18,
    radius: 1.08 + index * 0.07,
    dots: Array.from({ length: small ? 60 : 110 }, (_, i) => ({
      angle: (i / (small ? 60 : 110)) * Math.PI * 2,
      jitter: Math.random() * 0.05,
    })),
  }));
  // Filaments: glowing strands wrapped around the sphere on tilted circles.
  const filaments = Array.from({ length: small ? 16 : 28 }, () => ({
    tilt: Math.random() * Math.PI,
    turn: Math.random() * Math.PI * 2,
    radius: 0.55 + Math.random() * 0.5,
    length: 0.8 + Math.random() * 2.2,
    offset: Math.random() * Math.PI * 2,
    speed: (Math.random() - 0.5) * 0.9,
  }));
  const state = { name: "idle", current: { ...ORB_STATES.idle }, level: 0, burst: 0, tiltX: 0, tiltY: 0, targetX: 0, targetY: 0 };
  let width = 0;
  let height = 0;
  let frame = 0;
  let last = performance.now();
  let spin = 0;
  let visible = true;

  const resize = () => {
    const box = canvas.getBoundingClientRect();
    const dpr = Math.min(modest ? 1.25 : 2, window.devicePixelRatio || 1);
    width = Math.max(1, box.width);
    height = Math.max(1, box.height);
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    if (still) draw(0);
  };
  const sizer = new ResizeObserver(resize);
  sizer.observe(canvas);
  const watcher = new IntersectionObserver((entries) => {
    visible = entries.some((entry) => entry.isIntersecting);
  });
  watcher.observe(canvas);
  const onPointer = (event) => {
    const box = canvas.getBoundingClientRect();
    state.targetX = ((event.clientY - box.top) / box.height - 0.5) * 0.6;
    state.targetY = ((event.clientX - box.left) / box.width - 0.5) * 0.6;
  };
  canvas.addEventListener("pointermove", onPointer);

  function project(x, y, z, radius, cx, cy) {
    // Rotate around Y (spin + pointer) then X (tilt), then perspective.
    const ay = spin + state.tiltY;
    const cosY = Math.cos(ay);
    const sinY = Math.sin(ay);
    const x1 = x * cosY + z * sinY;
    const z1 = -x * sinY + z * cosY;
    const ax = 0.35 + state.tiltX;
    const cosX = Math.cos(ax);
    const sinX = Math.sin(ax);
    const y2 = y * cosX - z1 * sinX;
    const z2 = y * sinX + z1 * cosX;
    const scale = 2.6 / (2.6 + z2);
    return { px: cx + x1 * radius * scale, py: cy + y2 * radius * scale, depth: z2, scale };
  }

  function draw(time) {
    const t = time / 1000;
    const goal = ORB_STATES[state.name] || ORB_STATES.idle;
    for (const key of Object.keys(goal)) {
      state.current[key] += (goal[key] - state.current[key]) * 0.05;
    }
    const c = state.current;
    const speakPulse = state.name === "speaking" ? 0.35 + 0.35 * Math.abs(Math.sin(t * 8.5)) * (0.6 + 0.4 * Math.sin(t * 2.3)) : 0;
    const level = Math.max(state.level, speakPulse);
    state.burst *= 0.93;
    state.tiltX += (state.targetX - state.tiltX) * 0.04;
    state.tiltY += (state.targetY - state.tiltY) * 0.04;
    // The core drifts a little, like it is floating, and leans toward you.
    const cx = width / 2 + Math.sin(t * 0.37) * width * 0.035 + state.tiltY * width * 0.05;
    const cy = height / 2 + Math.cos(t * 0.29) * height * 0.03 + state.tiltX * height * 0.05;
    const base = Math.min(width, height) * 0.34;
    const breathe = 1 + 0.025 * Math.sin(t * 1.3) + level * 0.18 + state.burst * 0.25;
    const radius = base * breathe;

    ctx.clearRect(0, 0, width, height);
    ctx.globalCompositeOperation = "lighter";

    // Halo and core glow.
    const halo = ctx.createRadialGradient(cx, cy, radius * 0.6, cx, cy, radius * 1.7);
    halo.addColorStop(0, `rgba(255, 170, 60, ${0.1 * c.heat})`);
    halo.addColorStop(1, "rgba(255, 140, 20, 0)");
    ctx.fillStyle = halo;
    ctx.fillRect(0, 0, width, height);
    const glow = ctx.createRadialGradient(cx, cy, 0, cx, cy, radius * (0.8 + level * 0.3));
    glow.addColorStop(0, `rgba(255, 250, 230, ${0.85 * c.heat})`);
    glow.addColorStop(0.12, `rgba(255, 214, 130, ${0.6 * c.heat})`);
    glow.addColorStop(0.45, `rgba(230, 140, 40, ${0.2 * c.heat})`);
    glow.addColorStop(1, "rgba(120, 50, 0, 0)");
    ctx.fillStyle = glow;
    ctx.fillRect(0, 0, width, height);

    // Energy filaments.
    for (const f of filaments) {
      f.offset += f.speed * 0.012 * (1 + c.swirl * 3);
      const steps = 26;
      const cosT = Math.cos(f.tilt);
      const sinT = Math.sin(f.tilt);
      let previous = null;
      for (let i = 0; i <= steps; i += 1) {
        const a = f.offset + (i / steps) * f.length;
        const wave = 1 + 0.05 * Math.sin(a * 5 + t * 2) + level * 0.1;
        const x0 = Math.cos(a) * f.radius * wave;
        const y0 = Math.sin(a) * f.radius * wave;
        const x = x0 * Math.cos(f.turn) - y0 * sinT * Math.sin(f.turn);
        const y = y0 * cosT;
        const z = x0 * Math.sin(f.turn) + y0 * sinT * Math.cos(f.turn);
        const q = project(x, y, z, radius, cx, cy);
        if (previous) {
          const near = (1 - q.depth) / 2;
          const fade = Math.sin((i / steps) * Math.PI);
          ctx.strokeStyle = `rgba(255, ${180 + Math.round(near * 60)}, 90, ${(0.05 + near * 0.3) * fade * c.heat + level * 0.1})`;
          ctx.lineWidth = 0.6 + near * 0.9;
          ctx.beginPath();
          ctx.moveTo(previous.px, previous.py);
          ctx.lineTo(q.px, q.py);
          ctx.stroke();
        }
        previous = q;
      }
    }

    // Shell particles.
    for (const p of points) {
      const wobble = 1 + c.spread * Math.sin(t * 3 + p.phase) + level * 0.12 * Math.sin(t * 11 + p.phase * 3);
      const swirl = c.swirl * Math.sin(t * 0.8 + p.y * 3) * 0.6;
      const cs = Math.cos(swirl);
      const sn = Math.sin(swirl);
      const x = (p.x * cs - p.z * sn) * p.shell * wobble;
      const z = (p.x * sn + p.z * cs) * p.shell * wobble;
      const q = project(x, p.y * p.shell * wobble, z, radius, cx, cy);
      const near = (1 - q.depth) / 2;
      const flicker = 0.55 + 0.45 * Math.sin(t * 2.2 + p.phase);
      const alpha = Math.min(1, (0.2 + near * 0.85) * flicker * c.heat);
      const size = p.size * q.scale * (1 + level * 0.6);
      ctx.fillStyle = `rgba(255, ${170 + Math.round(near * 70)}, ${60 + Math.round(near * 90)}, ${alpha})`;
      if (p.streak && c.streak > 0.1) {
        const tail = project(x * 0.94, p.y * p.shell * wobble * 0.94, z * 0.94, radius, cx, cy);
        ctx.strokeStyle = ctx.fillStyle;
        ctx.lineWidth = size * 0.7;
        ctx.beginPath();
        ctx.moveTo(q.px, q.py);
        ctx.lineTo(q.px + (q.px - tail.px) * c.streak * 3, q.py + (q.py - tail.py) * c.streak * 3);
        ctx.stroke();
      } else {
        ctx.fillRect(q.px - size / 2, q.py - size / 2, size, size);
      }
    }

    // Orbital rings.
    for (const ring of rings) {
      const turn = t * ring.speed * (1 + c.swirl);
      for (const dot of ring.dots) {
        const a = dot.angle + turn;
        const rx = Math.cos(a) * ring.radius;
        const rz = Math.sin(a) * ring.radius;
        const ry = rz * Math.sin(ring.tilt);
        const q = project(rx, ry + dot.jitter, rz * Math.cos(ring.tilt), radius, cx, cy);
        const near = (1 - q.depth) / 2;
        ctx.fillStyle = `rgba(255, 200, 110, ${(0.08 + near * 0.35) * c.heat})`;
        ctx.fillRect(q.px, q.py, 1.4 * q.scale, 1.4 * q.scale);
      }
    }
    ctx.globalCompositeOperation = "source-over";
  }

  function loop(now) {
    frame = requestAnimationFrame(loop);
    if (!visible || document.hidden) return;
    if (frameGap && now - lastFrame < frameGap) return;
    lastFrame = now;
    const dt = Math.min(0.05, (now - last) / 1000);
    last = now;
    spin += dt * (state.current.spin + state.burst * 2);
    draw(now);
  }
  resize();
  if (!still) frame = requestAnimationFrame(loop);

  return {
    setState(name) {
      if (state.name === name) return;
      state.name = name;
      if (still) draw(performance.now());
    },
    setLevel(value) {
      state.level = Math.max(0, Math.min(1, value || 0));
    },
    burst() {
      state.burst = 1;
      if (still) draw(performance.now());
    },
    destroy() {
      cancelAnimationFrame(frame);
      sizer.disconnect();
      watcher.disconnect();
      canvas.removeEventListener("pointermove", onPointer);
    },
  };
}
