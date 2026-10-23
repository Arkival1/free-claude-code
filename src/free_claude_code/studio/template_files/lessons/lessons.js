(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const PRICES = { "First wave": 79, "Three-day course": 199, "Private coaching": 140 };
  const money = new Intl.NumberFormat("en-AU", { style: "currency", currency: "AUD" });

  // The waves: four layers of summed sine waves that swell towards the pointer.
  const canvas = $("waves"), ctx = canvas.getContext("2d");
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  let w = 0, h = 0, pointer = 0.5, pull = 0, on = true;
  function size() {
    const dpr = Math.min(devicePixelRatio || 1, 2);
    w = canvas.clientWidth; h = canvas.clientHeight;
    canvas.width = w * dpr; canvas.height = h * dpr; ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }
  new ResizeObserver(size).observe(canvas);
  size();
  const layers = [
    { y: 0.5, amp: 14, len: 380, speed: 0.25, colour: "#7cc6c0" },
    { y: 0.6, amp: 20, len: 300, speed: 0.4, colour: "#2b8c99" },
    { y: 0.72, amp: 26, len: 240, speed: 0.6, colour: "#146478" },
    { y: 0.86, amp: 18, len: 180, speed: 0.8, colour: "#0c3b4a" },
  ];
  function draw(t) {
    ctx.clearRect(0, 0, w, h);
    // The sun, low over the water.
    const g = ctx.createRadialGradient(w * 0.78, h * 0.34, 0, w * 0.78, h * 0.34, h * 0.32);
    g.addColorStop(0, "rgba(255, 236, 200, 0.95)"); g.addColorStop(0.25, "rgba(255, 190, 140, 0.6)"); g.addColorStop(1, "rgba(255, 190, 140, 0)");
    ctx.fillStyle = g; ctx.fillRect(0, 0, w, h);
    layers.forEach((l, i) => {
      ctx.beginPath();
      ctx.moveTo(0, h);
      for (let x = 0; x <= w + 8; x += 8) {
        const near = Math.exp(-(((x / w) - pointer) ** 2) / 0.02) * pull * (1 + i * 0.5);
        const y = h * l.y
          + Math.sin(x / l.len * Math.PI * 2 + t * l.speed) * l.amp
          + Math.sin(x / (l.len * 0.47) - t * l.speed * 1.3) * l.amp * 0.35
          - near * 26;
        ctx.lineTo(x, y);
      }
      ctx.lineTo(w, h); ctx.closePath();
      ctx.fillStyle = l.colour; ctx.fill();
      if (i < 3) { ctx.strokeStyle = "rgba(255, 255, 255, 0.35)"; ctx.lineWidth = 2; ctx.stroke(); }
    });
  }
  canvas.parentElement.addEventListener("pointermove", (e) => {
    const r = canvas.getBoundingClientRect();
    pointer = (e.clientX - r.left) / r.width; pull = 1;
  });
  canvas.parentElement.addEventListener("pointerleave", () => { pull = 0; });
  new IntersectionObserver((e) => { on = e[0].isIntersecting; }).observe(canvas);
  let start = performance.now(), smooth = 0;
  function loop(now) {
    requestAnimationFrame(loop);
    if (!on || document.hidden) return;
    smooth += (pull - smooth) * 0.05;
    const saved = pull; pull = smooth;
    draw(reduce ? 0 : (now - start) / 1000);
    pull = saved;
  }
  requestAnimationFrame(loop);

  // Lesson buttons fill in the form.
  document.querySelectorAll("[data-lesson]").forEach((a) => a.addEventListener("click", () => { $("lesson").value = a.dataset.lesson; }));
  const today = new Date(); today.setDate(today.getDate() + 1);
  // Tomorrow in the visitor's own time zone (toISOString would give UTC's).
  const tomorrow = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
  $("date").min = tomorrow;
  $("date").value = tomorrow;

  const form = $("booking");
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const err = $("err"), done = $("done");
    const name = $("name").value.trim(), people = Number($("people").value), day = $("date").value;
    err.textContent = "";
    if (!name) { err.textContent = "Add your name."; return $("name").focus(); }
    if (!Number.isInteger(people) || people < 1 || people > 6) { err.textContent = "Groups are 1 to 6 people."; return $("people").focus(); }
    if (!day || day < $("date").min) { err.textContent = "Pick a day from tomorrow on."; return $("date").focus(); }
    const lesson = $("lesson").value;
    const price = PRICES[lesson] * (lesson === "Private coaching" ? Math.ceil(people / 2) : people);
    const summary = `${lesson} for ${people}, ${new Date(`${day}T12:00`).toLocaleDateString("en-AU", { weekday: "long", day: "numeric", month: "long" })}: ${money.format(price)} on the day.`;
    done.hidden = false;
    if (form.dataset.endpoint) {
      done.textContent = "Sending…";
      const button = form.querySelector("[type=submit]");
      button.disabled = true;
      fetch(form.dataset.endpoint, { method: "POST", body: new FormData(form), headers: { Accept: "application/json" } })
        .then((r) => { if (!r.ok) throw new Error(); done.textContent = `Booked: ${summary}`; form.reset(); $("date").value = tomorrow; })
        .catch(() => { done.textContent = "That didn't send. Please email us instead."; })
        .finally(() => { button.disabled = false; });
      return;
    }
    location.href = `mailto:${form.dataset.email}?subject=${encodeURIComponent(`Lesson booking: ${name}`)}&body=${encodeURIComponent(`${summary}\nLevel: ${$("level").value}`)}`;
    done.textContent = `Your email app is opening with your booking: ${summary}`;
  });
})();
