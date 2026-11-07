// FCC Web kit: the small bits of script a kit site uses (FCC's own code).
// The phone menu, reveal on scroll, a light/dark switch, a picture viewer
// for galleries, the year in the footer, and forms that say thank you.
// Everything shows without it; it only adds polish.
(() => {
  document.documentElement.classList.add("js");
  const ready = (fn) => (document.readyState === "loading" ? document.addEventListener("DOMContentLoaded", fn) : fn());

  ready(() => {
    // Phone menu: the toggle opens and closes the panel; a link closes it.
    for (const nav of document.querySelectorAll(".nav")) {
      const toggle = nav.querySelector(".nav-toggle");
      if (!toggle) continue;
      toggle.addEventListener("click", () => {
        const open = nav.dataset.open !== "true";
        nav.dataset.open = String(open);
        toggle.setAttribute("aria-expanded", String(open));
      });
      nav.addEventListener("click", (event) => {
        if (event.target.closest(".nav-panel a")) {
          nav.dataset.open = "false";
          toggle.setAttribute("aria-expanded", "false");
        }
      });
    }

    // Reveal on scroll (shown at once when motion is reduced or unsupported).
    const reveals = document.querySelectorAll("[data-reveal]");
    const still = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (still || !("IntersectionObserver" in window)) reveals.forEach((item) => item.classList.add("shown"));
    else {
      const watcher = new IntersectionObserver(
        (entries) => {
          for (const entry of entries) {
            if (!entry.isIntersecting) continue;
            entry.target.classList.add("shown");
            watcher.unobserve(entry.target);
          }
        },
        { rootMargin: "0px 0px -8% 0px", threshold: 0.08 }
      );
      reveals.forEach((item, index) => {
        item.style.transitionDelay = `${Math.min(index % 4, 3) * 70}ms`;
        watcher.observe(item);
      });
    }

    // Light / dark: a [data-theme-toggle] button flips it and remembers it.
    const root = document.documentElement;
    try {
      const saved = localStorage.getItem("kit-theme");
      if (saved) root.dataset.theme = saved;
    } catch {
      /* storage may be off in a preview */
    }
    for (const button of document.querySelectorAll("[data-theme-toggle]")) {
      button.addEventListener("click", () => {
        root.dataset.theme = root.dataset.theme === "dark" ? "light" : "dark";
        try {
          localStorage.setItem("kit-theme", root.dataset.theme);
        } catch {
          /* fine */
        }
      });
    }

    // Gallery viewer: tap a picture to see it big; tap again or Escape closes.
    for (const gallery of document.querySelectorAll(".gallery")) {
      gallery.addEventListener("click", (event) => {
        const item = event.target.closest(".gallery > *");
        if (!item) return;
        const box = document.createElement("div");
        box.className = "lightbox";
        box.setAttribute("role", "dialog");
        box.setAttribute("aria-label", "Picture");
        box.append(item.cloneNode(true));
        const escape = (key) => {
          if (key.key === "Escape") close();
        };
        const close = () => {
          box.remove();
          document.removeEventListener("keydown", escape);
        };
        box.addEventListener("click", close);
        document.addEventListener("keydown", escape);
        document.body.append(box);
      });
    }

    for (const year of document.querySelectorAll("[data-year]")) year.textContent = String(new Date().getFullYear());

    // Forms with no address to send to say thank you instead of reloading.
    for (const form of document.querySelectorAll("form")) {
      form.addEventListener("submit", (event) => {
        if (form.getAttribute("action")) return;
        event.preventDefault();
        const note = document.createElement("p");
        note.className = "badge badge-dot";
        note.setAttribute("role", "status");
        note.textContent = form.dataset.thanks || "Thanks! We'll be in touch soon.";
        form.replaceWith(note);
      });
    }
  });
})();
