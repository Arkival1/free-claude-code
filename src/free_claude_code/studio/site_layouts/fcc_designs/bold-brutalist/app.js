// FCC design library: small, shared behaviours. Each one runs only when the
// page has the matching element, so every design can carry the same file.
(() => {
  "use strict";

  // Phone menu: the Menu button opens and closes the nav.
  const menu = document.querySelector(".menu");
  const nav = document.getElementById("nav");
  if (menu && nav) {
    menu.addEventListener("click", () => {
      const open = nav.classList.toggle("open");
      menu.setAttribute("aria-expanded", String(open));
    });
    nav.addEventListener("click", (event) => {
      if (event.target.closest("a")) {
        nav.classList.remove("open");
        menu.setAttribute("aria-expanded", "false");
      }
    });
  }

  // The year in the footer.
  for (const node of document.querySelectorAll("[data-year]")) {
    node.textContent = String(new Date().getFullYear());
  }

  // Tabs: buttons with data-tab show the panel with the same data-panel.
  for (const group of document.querySelectorAll("[data-tabs]")) {
    const buttons = [...group.querySelectorAll("[data-tab]")];
    const panels = [...group.querySelectorAll("[data-panel]")];
    const show = (name) => {
      for (const button of buttons) {
        const on = button.dataset.tab === name;
        button.setAttribute("aria-selected", String(on));
        button.tabIndex = on ? 0 : -1;
      }
      for (const panel of panels) panel.hidden = panel.dataset.panel !== name;
    };
    for (const button of buttons) {
      button.addEventListener("click", () => show(button.dataset.tab));
      // Left/Right arrows (and Home/End) move between tabs, as screen readers expect.
      button.addEventListener("keydown", (event) => {
        const at = buttons.indexOf(button);
        const moves = { ArrowRight: at + 1, ArrowLeft: at - 1, Home: 0, End: buttons.length - 1 };
        if (event.altKey || event.ctrlKey || event.metaKey || !Object.hasOwn(moves, event.key)) return;
        event.preventDefault();
        const next = buttons[(moves[event.key] + buttons.length) % buttons.length];
        show(next.dataset.tab);
        next.focus();
      });
    }
    if (buttons[0]) show(buttons[0].dataset.tab);
  }

  // Filters: buttons with data-filter show the items of that data-kind.
  for (const group of document.querySelectorAll("[data-filters]")) {
    const buttons = [...group.querySelectorAll("[data-filter]")];
    const items = [...document.querySelectorAll("[data-kind]")];
    for (const button of buttons) {
      button.addEventListener("click", () => {
        const kind = button.dataset.filter;
        for (const other of buttons) other.setAttribute("aria-pressed", String(other === button));
        for (const item of items) item.hidden = kind !== "all" && item.dataset.kind !== kind;
      });
    }
  }

  // A cart count: each data-add button adds one.
  const cart = document.querySelector("[data-cart]");
  if (cart) {
    let count = 0;
    for (const button of document.querySelectorAll("[data-add]")) {
      button.addEventListener("click", () => {
        count += 1;
        cart.textContent = String(count);
        button.textContent = "Added";
        setTimeout(() => { button.textContent = "Add to cart"; }, 1200);
      });
    }
  }

  // Forms: check the fields, then open the visitor's email app addressed to
  // data-email (no data leaves the page until they press send there).
  for (const form of document.querySelectorAll("form[data-email]")) {
    const note = form.querySelector(".note");
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const missing = [...form.querySelectorAll("[required]")].find((field) => !field.value.trim());
      const email = form.querySelector("input[type=email]");
      const say = (text) => { if (note) note.textContent = text; };
      if (missing) {
        say("Please fill in every field.");
        missing.focus();
        return;
      }
      if (email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.value.trim())) {
        say("That email address doesn't look right.");
        email.focus();
        return;
      }
      const lines = [...new FormData(form)].map(([key, value]) => `${key}: ${value}`);
      const subject = encodeURIComponent(`New message from ${document.title}`);
      const body = encodeURIComponent(lines.join("\n"));
      say("Thanks! Your email app will open with the message ready to send.");
      window.location.href = `mailto:${form.dataset.email}?subject=${subject}&body=${body}`;
      form.reset();
    });
  }
})();
