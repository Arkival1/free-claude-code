"""The business starter: a multi-page site like a café's, salon's, or shop's.

Five pages share one header and footer: a full-bleed photo hero, a header
that turns solid on scroll, a phone menu, tabs with prices, a gallery with a
lightbox, and a contact form. Pictures start as drawn placeholders marked
data-placeholder, which check_project asks the Builder to swap for photos.
Text uses string.Template, so a literal dollar sign is written $$.
"""

PAGES = (
    ("index.html", "Home"),
    ("about.html", "About"),
    ("services.html", "Services"),
    ("gallery.html", "Gallery"),
    ("contact.html", "Contact"),
)
PLACEHOLDER_TEXT: tuple[str, ...] = (
    "Say what makes this one special.",
    "12 Your Street, Your Town",
    "(000) 000-0000",
    "hello@example.com",
    "Photo credits go here.",
)
"""Placeholder copy only this template has, which a finished site replaces."""

_ICONS = {
    "star": '<path d="m12 3 2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1-4.4-4.3 6.1-.9z"/>',
    "heart": '<path d="M12 20s-7-4.4-9.2-9A5 5 0 0 1 12 6a5 5 0 0 1 9.2 5c-2.2 4.6-9.2 9-9.2 9z"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "pin": '<path d="M12 21s-7-6.2-7-12a7 7 0 0 1 14 0c0 5.8-7 12-7 12z"/><circle cx="12" cy="9" r="2.5"/>',
    "menu": '<path d="M4 7h16M4 12h16M4 17h16"/>',
    "instagram": '<rect x="3" y="3" width="18" height="18" rx="5"/><circle cx="12" cy="12" r="4"/><circle cx="17.5" cy="6.5" r="1"/>',
    "facebook": '<path d="M14 8h3V4h-3a4 4 0 0 0-4 4v3H7v4h3v6h4v-6h3l1-4h-4V8z"/>',
    "arrow": '<path d="M5 12h14M13 6l6 6-6 6"/>',
}


def _icon(name: str) -> str:
    return (
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
        f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{_ICONS[name]}</svg>'
    )


def _art(dark: str, mid: str, light: str) -> str:
    """A warm abstract picture that stands in until a real photo is saved."""
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1600 1000" width="1600" height="1000">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{dark}"/>
      <stop offset=".55" stop-color="{mid}"/>
      <stop offset="1" stop-color="{light}"/>
    </linearGradient>
    <radialGradient id="l" cx=".72" cy=".28" r=".6">
      <stop offset="0" stop-color="#fff3df" stop-opacity=".5"/>
      <stop offset="1" stop-color="#fff3df" stop-opacity="0"/>
    </radialGradient>
  </defs>
  <rect width="1600" height="1000" fill="url(#g)"/>
  <rect width="1600" height="1000" fill="url(#l)"/>
  <g fill="#fff" fill-opacity=".07">
    <circle cx="1240" cy="740" r="330"/>
    <circle cx="280" cy="170" r="230"/>
    <circle cx="820" cy="520" r="120"/>
  </g>
</svg>
"""


def _head(page: str) -> str:
    title = "$title" if page == "Home" else f"{page} · $title"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <meta name="description" content="$title: {page.lower() if page != "Home" else "welcome"}.">
  <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><rect width='100' height='100' rx='22' fill='%232e1b10'/><text x='50' y='71' font-size='60' font-family='Georgia,serif' font-weight='700' text-anchor='middle' fill='%23f3e3cf'>$initial</text></svg>">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Playfair+Display:wght@600;700&display=swap">
  <link rel="stylesheet" href="styles.css">
  <script>document.documentElement.classList.add("js");</script>
</head>
<body>
  <a class="skip" href="#main">Skip to content</a>
"""


def _header(page: str) -> str:
    links = "\n".join(
        f'        <a href="{path}"{' aria-current="page"' if name == page else ""}>{name}</a>'
        for path, name in PAGES
    )
    return f"""  <header class="site-header">
    <div class="container nav">
      <a class="brand" href="index.html">$title</a>
      <button class="nav-toggle" type="button" aria-expanded="false" aria-controls="menu" aria-label="Open menu">{_icon("menu")}</button>
      <nav id="menu" class="menu" aria-label="Main">
{links}
        <a class="button" href="contact.html">Book now</a>
      </nav>
    </div>
  </header>
"""


def _page_hero(eyebrow: str, heading: str, picture: str) -> str:
    return f"""    <section class="hero page">
      <img class="hero-media" src="images/{picture}" alt="" width="1600" height="1000" data-placeholder>
      <div class="container hero-content">
        <p class="eyebrow">{eyebrow}</p>
        <h1>{heading}</h1>
      </div>
    </section>
"""


_FOOTER = f"""  <footer class="site-footer">
    <div class="container footer-grid">
      <div>
        <a class="brand" href="index.html">$title</a>
        <p>A short line that says what this is and who it is for.</p>
        <div class="social">
          <a href="https://www.instagram.com/" aria-label="Instagram">{_icon("instagram")}</a>
          <a href="https://www.facebook.com/" aria-label="Facebook">{_icon("facebook")}</a>
        </div>
      </div>
      <div>
        <h2>Pages</h2>
        <ul>
{chr(10).join(f'          <li><a href="{path}">{name}</a></li>' for path, name in PAGES)}
        </ul>
      </div>
      <div>
        <h2>Opening hours</h2>
        <ul>
          <li>Mon&ndash;Fri: 8am &ndash; 6pm</li>
          <li>Sat&ndash;Sun: 9am &ndash; 4pm</li>
        </ul>
      </div>
      <div>
        <h2>Visit us</h2>
        <ul>
          <li>12 Your Street, Your Town</li>
          <li><a href="tel:+10000000000">(000) 000-0000</a></li>
          <li><a href="mailto:hello@example.com">hello@example.com</a></li>
        </ul>
      </div>
    </div>
    <div class="container footer-bottom">
      <p>&copy; <span data-year></span> $title. All rights reserved.</p>
      <p>Photo credits go here.</p>
    </div>
  </footer>
  <script src="app.js"></script>
</body>
</html>
"""


def _page(name: str, main: str) -> str:
    return f'{_head(name)}{_header(name)}  <main id="main">\n{main}  </main>\n{_FOOTER}'


_HOME = _page(
    "Home",
    f"""    <section class="hero">
      <img class="hero-media" src="images/hero.svg" alt="" width="1600" height="1000" data-placeholder>
      <div class="container hero-content">
        <p class="eyebrow">Welcome</p>
        <h1>$title</h1>
        <p class="lead">A short line that says what this is and who it is for.</p>
        <div class="actions">
          <a class="button" href="contact.html">Book a visit</a>
          <a class="button ghost" href="services.html">See our services</a>
        </div>
        <div class="facts">
          <p><strong>Open every day</strong>Mon&ndash;Fri 8am &ndash; 6pm</p>
          <p><strong>Find us</strong>12 Your Street, Your Town</p>
          <p><strong>Call us</strong><a href="tel:+10000000000">(000) 000-0000</a></p>
        </div>
      </div>
    </section>
    <section class="section">
      <div class="container split">
        <img src="images/photo-1.svg" alt="Inside $title" width="1600" height="1000" data-placeholder class="reveal">
        <div class="reveal">
          <p class="eyebrow">Our story</p>
          <h2>Made with care</h2>
          <p>Tell the story here.</p>
          <a class="link-arrow" href="about.html">About us {_icon("arrow")}</a>
        </div>
      </div>
    </section>
    <section class="section alt">
      <div class="container">
        <div class="section-head reveal">
          <p class="eyebrow">Why people come back</p>
          <h2>What we do best</h2>
        </div>
        <div class="grid">
          <article class="card reveal"><div class="icon">{_icon("star")}</div><h3>Quality first</h3><p>A benefit, not a feature.</p></article>
          <article class="card reveal"><div class="icon">{_icon("heart")}</div><h3>Friendly people</h3><p>A benefit, not a feature.</p></article>
          <article class="card reveal"><div class="icon">{_icon("clock")}</div><h3>Open when you need us</h3><p>A benefit, not a feature.</p></article>
        </div>
      </div>
    </section>
    <section class="section">
      <div class="container">
        <div class="section-head reveal">
          <p class="eyebrow">Favourites</p>
          <h2>Popular right now</h2>
        </div>
        <div class="grid">
          <a class="card photo reveal" href="services.html"><img src="images/photo-2.svg" alt="First favourite" width="1600" height="1000" data-placeholder><div class="card-body"><h3>First</h3><p>What it is.</p></div></a>
          <a class="card photo reveal" href="services.html"><img src="images/photo-3.svg" alt="Second favourite" width="1600" height="1000" data-placeholder><div class="card-body"><h3>Second</h3><p>What it is.</p></div></a>
          <a class="card photo reveal" href="services.html"><img src="images/photo-1.svg" alt="Third favourite" width="1600" height="1000" data-placeholder><div class="card-body"><h3>Third</h3><p>What it is.</p></div></a>
        </div>
      </div>
    </section>
    <section class="section dark">
      <div class="container">
        <blockquote class="quote reveal">“It changed how I work.”<cite>A happy customer</cite></blockquote>
      </div>
    </section>
    <section class="section cta">
      <div class="container reveal">
        <h2>Come and see us</h2>
        <p class="lead center">A short line that says what this is and who it is for.</p>
        <div class="actions"><a class="button" href="contact.html">Book a visit</a><a class="button ghost dark-text" href="gallery.html">Look around</a></div>
      </div>
    </section>
""",
)

_ABOUT = _page(
    "About",
    _page_hero("About us", "Our story", "photo-1.svg")
    + f"""    <section class="section">
      <div class="container split">
        <div class="reveal">
          <p class="eyebrow">How it started</p>
          <h2>Where we come from</h2>
          <p>Tell the story here.</p>
        </div>
        <img src="images/photo-2.svg" alt="The team at work" width="1600" height="1000" data-placeholder class="reveal">
      </div>
    </section>
    <section class="section alt">
      <div class="container">
        <div class="section-head reveal"><p class="eyebrow">What we believe</p><h2>Our values</h2></div>
        <div class="grid">
          <article class="card reveal"><div class="icon">{_icon("star")}</div><h3>Craft</h3><p>A benefit, not a feature.</p></article>
          <article class="card reveal"><div class="icon">{_icon("heart")}</div><h3>Care</h3><p>A benefit, not a feature.</p></article>
          <article class="card reveal"><div class="icon">{_icon("pin")}</div><h3>Community</h3><p>A benefit, not a feature.</p></article>
        </div>
      </div>
    </section>
    <section class="section cta">
      <div class="container reveal">
        <h2>Meet us in person</h2>
        <div class="actions"><a class="button" href="contact.html">Get in touch</a></div>
      </div>
    </section>
""",
)


def _prices(panel: str) -> str:
    rows = "\n".join(
        f"""            <li><h3>{name}</h3><span class="price">$$0</span><p>Say what makes this one special.</p></li>"""
        for name in (f"{panel} one", f"{panel} two", f"{panel} three", f"{panel} four")
    )
    return f'          <ul class="prices">\n{rows}\n          </ul>\n'


_SERVICES = _page(
    "Services",
    _page_hero("What we offer", "Services and prices", "photo-3.svg")
    + f"""    <section class="section">
      <div class="container tabs" data-tabs>
        <div class="section-head reveal"><p class="eyebrow">Choose a category</p><h2>Everything we offer</h2></div>
        <div role="tablist" aria-label="Categories">
          <button class="tab" type="button" role="tab" id="tab-1" aria-controls="panel-1" aria-selected="true">Popular</button>
          <button class="tab" type="button" role="tab" id="tab-2" aria-controls="panel-2" aria-selected="false" tabindex="-1">Classics</button>
          <button class="tab" type="button" role="tab" id="tab-3" aria-controls="panel-3" aria-selected="false" tabindex="-1">Extras</button>
        </div>
        <div role="tabpanel" id="panel-1" aria-labelledby="tab-1" tabindex="0">
{_prices("Popular")}        </div>
        <div role="tabpanel" id="panel-2" aria-labelledby="tab-2" tabindex="0" hidden>
{_prices("Classic")}        </div>
        <div role="tabpanel" id="panel-3" aria-labelledby="tab-3" tabindex="0" hidden>
{_prices("Extra")}        </div>
      </div>
    </section>
    <section class="section cta alt">
      <div class="container reveal">
        <h2>Ready when you are</h2>
        <div class="actions"><a class="button" href="contact.html">Book now</a></div>
      </div>
    </section>
""",
)

_SHOTS = (
    "hero.svg",
    "photo-1.svg",
    "photo-2.svg",
    "photo-3.svg",
    "photo-2.svg",
    "photo-1.svg",
)
_GALLERY = _page(
    "Gallery",
    _page_hero("Take a look", "Gallery", "photo-2.svg")
    + """    <section class="section">
      <div class="container">
        <div class="gallery">
"""
    + "\n".join(
        f'          <button type="button" data-shot aria-label="Open picture {n}"><img src="images/{name}" alt="Picture {n}" width="1600" height="1000" loading="lazy" data-placeholder></button>'
        for n, name in enumerate(_SHOTS, start=1)
    )
    + """
        </div>
      </div>
    </section>
    <dialog class="lightbox" id="lightbox" aria-label="Picture viewer">
      <figure>
        <img alt="" width="1600" height="1000">
        <figcaption></figcaption>
      </figure>
      <div class="lightbox-bar">
        <button type="button" data-prev aria-label="Previous picture">&lsaquo;</button>
        <button type="button" data-close aria-label="Close">✕</button>
        <button type="button" data-next aria-label="Next picture">&rsaquo;</button>
      </div>
    </dialog>
""",
)

_CONTACT = _page(
    "Contact",
    _page_hero("Say hello", "Contact and booking", "hero.svg")
    + f"""    <section class="section">
      <div class="container split top">
        <form class="card form reveal" id="contact-form" novalidate data-endpoint="" data-email="">
          <h2>Send us a message</h2>
          <div class="row2">
            <label for="name">Name <input id="name" name="name" required autocomplete="name"><span class="error" id="name-error"></span></label>
            <label for="email">Email <input id="email" name="email" type="email" required autocomplete="email"><span class="error" id="email-error"></span></label>
          </div>
          <div class="row2">
            <label for="phone">Phone (optional) <input id="phone" name="phone" type="tel" autocomplete="tel"><span class="error" id="phone-error"></span></label>
            <label for="date">Preferred date <input id="date" name="date" type="date"><span class="error" id="date-error"></span></label>
          </div>
          <label for="message">Message <textarea id="message" name="message" rows="5" required></textarea><span class="error" id="message-error"></span></label>
          <button class="button" type="submit">Send message</button>
          <p class="status" id="form-status" role="status"></p>
        </form>
        <div class="reveal">
          <h2>Find us</h2>
          <p class="with-icon">{_icon("pin")}<span>12 Your Street, Your Town</span></p>
          <p><a class="link-arrow" href="https://www.openstreetmap.org/search?query=Your%20Town">Open in maps {_icon("arrow")}</a></p>
          <p><a href="tel:+10000000000">(000) 000-0000</a><br><a href="mailto:hello@example.com">hello@example.com</a></p>
          <table class="hours">
            <caption>Opening hours</caption>
            <tr><th scope="row">Monday &ndash; Friday</th><td>8am &ndash; 6pm</td></tr>
            <tr><th scope="row">Saturday</th><td>9am &ndash; 4pm</td></tr>
            <tr><th scope="row">Sunday</th><td>9am &ndash; 4pm</td></tr>
          </table>
        </div>
      </div>
    </section>
""",
)

_STYLES = """/* Change the look here: colours, fonts, and sizes are variables. */
:root {
  --ink: #1f1a17;
  --paper: #faf6f0;
  --surface: #ffffff;
  --muted: #625850;
  --line: #e8dfd3;
  --accent: #9c4f17;
  --accent-dark: #7d3f12;
  --accent-soft: #f3e3d3;
  --highlight: #f0b37e;
  --dark: #171310;
  --on-dark: #f6efe7;
  --radius: 14px;
  --gap: clamp(16px, 4vw, 32px);
  --page: 1160px;
  --display: "Playfair Display", Georgia, "Times New Roman", serif;
  --body: "Inter", system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
}
*, *::before, *::after { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body { margin: 0; font-family: var(--body); font-size: 17px; line-height: 1.65; color: var(--ink); background: var(--paper); }
img, svg { max-width: 100%; display: block; }
img { height: auto; }
h1, h2, h3 { font-family: var(--display); font-weight: 700; line-height: 1.12; margin: 0 0 0.5em; }
h1 { font-size: clamp(2.5rem, 7vw, 4.8rem); }
h2 { font-size: clamp(1.8rem, 4.5vw, 2.8rem); }
h3 { font-size: 1.3rem; }
p { margin: 0 0 1em; }
a { color: var(--accent); transition: color 0.2s, opacity 0.2s, background-color 0.2s; }
a:hover { color: var(--accent-dark); }
:focus-visible { outline: 3px solid var(--highlight); outline-offset: 3px; }
.container { width: min(var(--page), 100% - 2 * var(--gap)); margin-inline: auto; }
.skip { position: absolute; left: -999px; top: 8px; z-index: 100; padding: 10px 14px; border-radius: 8px; background: var(--surface); color: var(--ink); }
.skip:focus { left: 8px; }
.eyebrow { margin: 0 0 12px; color: var(--accent); font-size: 0.8rem; font-weight: 600; letter-spacing: 0.18em; text-transform: uppercase; }
.lead { max-width: 36rem; font-size: 1.15rem; }
.center { margin-inline: auto; }
.button {
  display: inline-flex; align-items: center; justify-content: center; gap: 8px;
  min-height: 48px; padding: 12px 26px; border: 2px solid var(--accent); border-radius: 999px;
  background: var(--accent); color: #fff; font-weight: 600; text-decoration: none; cursor: pointer;
  transition: transform 0.15s, background-color 0.2s, border-color 0.2s, color 0.2s;
}
.button:hover { transform: translateY(-2px); background: var(--accent-dark); border-color: var(--accent-dark); color: #fff; }
.button.ghost { background: transparent; border-color: currentColor; color: #fff; }
.button.ghost:hover { background: rgb(255 255 255 / 0.14); }
.button.ghost.dark-text { color: var(--ink); }
.button.ghost.dark-text:hover { background: var(--accent-soft); }

/* Header: over the photo at the top, solid once you scroll. */
.site-header { position: fixed; inset: 0 0 auto; z-index: 50; color: var(--on-dark); transition: background-color 0.3s, box-shadow 0.3s; }
.site-header.scrolled { background: rgb(23 19 16 / 0.96); box-shadow: 0 6px 24px rgb(0 0 0 / 0.18); }
.site-header.open { background: var(--dark); }
.nav { display: flex; align-items: center; justify-content: space-between; gap: 16px; min-height: 76px; }
.brand { display: inline-flex; align-items: center; min-height: 44px; color: inherit; font-family: var(--display); font-size: 1.5rem; font-weight: 700; text-decoration: none; }
.brand:hover { color: inherit; }
.menu { display: flex; align-items: center; gap: 4px; }
.menu a { display: inline-flex; align-items: center; min-height: 44px; padding: 10px 14px; border-radius: 999px; color: inherit; font-weight: 500; text-decoration: none; }
.menu a:hover { background: rgb(255 255 255 / 0.12); color: #fff; }
.menu a[aria-current="page"] { color: var(--highlight); }
.menu .button { margin-left: 8px; color: #fff; }
.nav-toggle { display: none; width: 48px; height: 48px; place-items: center; border: 1px solid rgb(255 255 255 / 0.4); border-radius: 12px; background: transparent; color: inherit; cursor: pointer; }
.nav-toggle svg { width: 24px; height: 24px; }
@media (max-width: 860px) {
  .nav-toggle { display: inline-grid; }
  .menu { display: none; position: fixed; inset: 76px 0 0; flex-direction: column; align-items: stretch; overflow-y: auto; padding: 12px var(--gap) 32px; background: var(--dark); }
  .menu a { font-size: 1.15rem; border-bottom: 1px solid rgb(255 255 255 / 0.08); }
  .menu.open { display: flex; }
  .menu a { padding: 16px 10px; border-radius: 0; }
  .menu .button { margin: 20px 0 0; border-radius: 999px; border-bottom: 0; }
}

/* Hero: a full-width photo with a dark fade so the words stay readable. */
.hero { position: relative; isolation: isolate; display: flex; align-items: flex-end; min-height: min(92svh, 860px); overflow: hidden; background: var(--dark); color: var(--on-dark); }
.hero.page { min-height: clamp(340px, 52svh, 520px); }
.hero-media { position: absolute; inset: 0; z-index: -2; width: 100%; height: 100%; object-fit: cover; }
.hero::after {
  content: ""; position: absolute; inset: 0; z-index: -1;
  background:
    linear-gradient(90deg, rgb(10 8 6 / 0.72) 0%, rgb(10 8 6 / 0.35) 60%, rgb(10 8 6 / 0.15) 100%),
    linear-gradient(180deg, rgb(10 8 6 / 0.55) 0%, rgb(10 8 6 / 0.2) 40%, rgb(10 8 6 / 0.85) 100%);
}
.hero h1, .hero .lead { text-shadow: 0 2px 18px rgb(0 0 0 / 0.35); }
.hero-content { padding-block: 140px clamp(48px, 8vw, 96px); }
.hero h1 { max-width: 14ch; color: #fff; }
.hero .lead { color: rgb(255 255 255 / 0.9); }
.hero .eyebrow { color: var(--highlight); }
.hero a:not(.button) { color: #fff; }
.actions { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 28px; }
.facts { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 190px), 1fr)); gap: 8px 32px; margin-top: 48px; padding-top: 24px; border-top: 1px solid rgb(255 255 255 / 0.25); }
.facts p { margin: 0; }
.facts strong { display: block; color: #fff; font-family: var(--display); font-size: 1.15rem; }

/* Sections */
.section { padding-block: clamp(56px, 10vw, 112px); }
.section.alt { background: var(--surface); }
.section.dark { background: var(--dark); color: var(--on-dark); }
.section-head { max-width: 40rem; margin-bottom: 40px; }
.split { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 380px), 1fr)); gap: clamp(28px, 5vw, 64px); align-items: center; }
.split.top { align-items: start; }
.split > img { width: 100%; aspect-ratio: 4 / 3; object-fit: cover; border-radius: var(--radius); }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 260px), 1fr)); gap: var(--gap); }
.card { display: block; padding: 28px; border: 1px solid var(--line); border-radius: var(--radius); background: var(--surface); color: inherit; text-decoration: none; transition: transform 0.2s, box-shadow 0.2s; }
.card:hover { transform: translateY(-4px); box-shadow: 0 18px 40px rgb(31 26 23 / 0.08); color: inherit; }
.card p { margin: 0; color: var(--muted); }
.card.photo { padding: 0; overflow: hidden; }
.card.photo img { width: 100%; aspect-ratio: 4 / 3; object-fit: cover; }
.card-body { padding: 22px 24px 26px; }
.icon { display: grid; place-items: center; width: 48px; height: 48px; margin-bottom: 18px; border-radius: 12px; background: var(--accent-soft); color: var(--accent); }
.icon svg { width: 24px; height: 24px; }
.link-arrow { display: inline-flex; align-items: center; gap: 6px; min-height: 44px; font-weight: 600; text-decoration: none; }
.link-arrow svg, .with-icon svg { width: 20px; height: 20px; flex: none; }
.with-icon { display: flex; gap: 10px; align-items: center; }
.quote { max-width: 46rem; margin: 0 auto; font-family: var(--display); font-size: clamp(1.4rem, 3.4vw, 2.2rem); line-height: 1.35; text-align: center; }
.quote cite { display: block; margin-top: 20px; color: var(--highlight); font-family: var(--body); font-size: 1rem; font-style: normal; }
.cta { text-align: center; }
.cta .actions { justify-content: center; }

/* Tabs with prices */
[role="tablist"] { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 28px; }
.tab { min-height: 44px; padding: 10px 20px; border: 1px solid var(--line); border-radius: 999px; background: var(--surface); color: var(--ink); font: inherit; font-weight: 600; cursor: pointer; transition: background-color 0.2s, color 0.2s, border-color 0.2s; }
.tab:hover { border-color: var(--accent); }
.tab[aria-selected="true"] { border-color: var(--accent); background: var(--accent); color: #fff; }
.prices { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 320px), 1fr)); gap: 4px 48px; margin: 0; padding: 0; list-style: none; }
.prices li { display: grid; grid-template-columns: 1fr auto; gap: 4px 16px; padding: 18px 0; border-bottom: 1px dashed var(--line); }
.prices h3 { margin: 0; font-size: 1.15rem; }
.prices .price { color: var(--accent); font-weight: 700; }
.prices p { grid-column: 1 / -1; margin: 0; color: var(--muted); font-size: 0.95rem; }

/* Gallery and picture viewer */
.gallery { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 240px), 1fr)); gap: 12px; }
.gallery button { padding: 0; overflow: hidden; border: 0; border-radius: var(--radius); background: none; cursor: zoom-in; }
.gallery img { width: 100%; aspect-ratio: 1; object-fit: cover; transition: transform 0.4s; }
.gallery button:hover img { transform: scale(1.05); }
.lightbox { max-width: min(1100px, 94vw); padding: 0; border: 0; background: transparent; color: #fff; }
.lightbox::backdrop { background: rgb(10 8 6 / 0.9); }
.lightbox figure { margin: 0; }
.lightbox img { width: auto; max-height: 78vh; margin-inline: auto; border-radius: var(--radius); }
.lightbox figcaption { margin-top: 10px; text-align: center; }
.lightbox-bar { display: flex; justify-content: center; gap: 12px; margin-top: 12px; }
.lightbox-bar button { min-width: 48px; min-height: 48px; border: 1px solid rgb(255 255 255 / 0.5); border-radius: 999px; background: rgb(0 0 0 / 0.4); color: #fff; font-size: 1.2rem; cursor: pointer; }
.lightbox-bar button:hover { background: rgb(255 255 255 / 0.15); }

/* Contact form */
.form { display: grid; gap: 16px; }
.form label { display: grid; gap: 6px; font-size: 0.95rem; font-weight: 600; }
.form input, .form textarea { min-height: 48px; padding: 12px 14px; border: 1px solid #cfc3b5; border-radius: 10px; background: var(--surface); color: var(--ink); font: inherit; font-weight: 400; }
.form input:focus, .form textarea:focus { outline: 3px solid var(--accent-soft); border-color: var(--accent); }
.form [aria-invalid="true"] { border-color: #a3261b; }
.row2 { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 200px), 1fr)); gap: 16px; }
.error { min-height: 1.2em; color: #a3261b; font-size: 0.9rem; font-weight: 500; }
.status { margin: 0; color: #2f6b3a; font-weight: 600; }
.hours { width: 100%; border-collapse: collapse; }
.hours caption { margin-bottom: 8px; font-family: var(--display); font-size: 1.3rem; font-weight: 700; text-align: left; }
.hours th, .hours td { padding: 10px 0; border-bottom: 1px solid var(--line); text-align: left; font-weight: 400; }
.hours td { text-align: right; }

/* Footer */
.site-footer { padding-block: 64px 28px; background: var(--dark); color: #d6ccc1; font-size: 0.95rem; }
.site-footer a { color: #d6ccc1; text-decoration: none; }
.site-footer a:hover { color: #fff; }
.site-footer .brand { color: #fff; }
.footer-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 200px), 1fr)); gap: 32px; }
.site-footer h2 { margin-bottom: 14px; color: #fff; font-family: var(--body); font-size: 1rem; letter-spacing: 0.08em; text-transform: uppercase; }
.site-footer h2::after { content: none; }
.site-footer ul { display: grid; gap: 4px; margin: 0; padding: 0; list-style: none; }
.site-footer li a { display: inline-flex; align-items: center; min-height: 36px; }
.social { display: flex; gap: 8px; margin-top: 16px; }
.social a { display: grid; place-items: center; width: 44px; height: 44px; border: 1px solid rgb(255 255 255 / 0.25); border-radius: 999px; }
.social svg { width: 20px; height: 20px; }
.footer-bottom { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 8px 24px; margin-top: 48px; padding-top: 20px; border-top: 1px solid rgb(255 255 255 / 0.12); font-size: 0.875rem; }
.footer-bottom p { margin: 0; }

/* Gentle fade-in as sections scroll into view. */
.js .reveal { opacity: 0; transform: translateY(24px); transition: opacity 0.7s ease, transform 0.7s ease; }
.js .reveal.in { opacity: 1; transform: none; }
@media (prefers-reduced-motion: reduce) {
  html { scroll-behavior: auto; }
  .js .reveal { opacity: 1; transform: none; transition: none; }
}
"""

FORM_JS = """// Contact form: clear messages for each field. A message is never lost:
// with a form service address (for example Formspree) in data-endpoint it is
// sent there; without one, the visitor's email app opens with the message
// addressed to the business (data-email, or the page's first email link).
for (const form of document.querySelectorAll("form[data-endpoint], #contact-form")) {
  const status = form.querySelector("[role=status]");
  const thanks = form.dataset.thanks || "Thank you! We'll reply within one working day.";
  const say = (text) => { if (status) status.textContent = text; };
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    let first = null;
    for (const field of form.querySelectorAll("input, textarea")) {
      const validity = field.validity;
      let message = "";
      if (validity.valueMissing) message = "Please fill this in.";
      else if (validity.typeMismatch) message = "Please check this is right.";
      field.setAttribute("aria-invalid", String(!validity.valid));
      const error = field.id && document.getElementById(field.id + "-error");
      if (error) error.textContent = message;
      if (!validity.valid && !first) first = field;
    }
    if (first) {
      say("");
      first.focus();
      return;
    }
    const endpoint = form.dataset.endpoint;
    if (endpoint) {
      say("Sending…");
      fetch(endpoint, { method: "POST", body: new FormData(form), headers: { Accept: "application/json" } })
        .then((response) => {
          if (!response.ok) throw new Error(String(response.status));
          say(thanks);
          form.reset();
        })
        .catch(() => say("Sorry, that didn't send. Please call or email us instead."));
      return;
    }
    const link = document.querySelector('a[href^="mailto:"]');
    const to = form.dataset.email || (link ? link.getAttribute("href").slice(7).split("?")[0] : "");
    if (!to) {
      say("Sorry, this form isn't connected yet. Please call or email us instead.");
      return;
    }
    const data = new FormData(form);
    const lines = [];
    for (const [key, value] of data.entries()) {
      if (String(value).trim()) lines.push(key + ": " + value);
    }
    const subject = "Website message from " + (data.get("name") || data.get("email") || "a visitor");
    window.location.href = "mailto:" + to + "?subject=" + encodeURIComponent(subject) +
      "&body=" + encodeURIComponent(lines.join("\\n"));
    say("Your email app is opening with your message. Press send there and it reaches us.");
  });
}
"""

_SCRIPT = (
    """// Shared by every page: header, menu, tabs, gallery, contact form, fade-ins.
const header = document.querySelector(".site-header");
const toggle = document.querySelector(".nav-toggle");
const menu = document.getElementById("menu");

function onScroll() {
  header.classList.toggle("scrolled", window.scrollY > 24);
}
onScroll();
addEventListener("scroll", onScroll, { passive: true });

function setMenu(open) {
  menu.classList.toggle("open", open);
  header.classList.toggle("open", open);
  toggle.setAttribute("aria-expanded", String(open));
  toggle.setAttribute("aria-label", open ? "Close menu" : "Open menu");
  document.body.style.overflow = open ? "hidden" : "";
}
toggle.addEventListener("click", () => setMenu(!menu.classList.contains("open")));
addEventListener("keydown", (event) => {
  if (event.key === "Escape" && menu.classList.contains("open")) {
    setMenu(false);
    toggle.focus();
  }
});

for (const year of document.querySelectorAll("[data-year]")) {
  year.textContent = new Date().getFullYear();
}

// Tabs: click, or use the arrow keys, Home, and End.
for (const tabs of document.querySelectorAll("[data-tabs]")) {
  const buttons = [...tabs.querySelectorAll('[role="tab"]')];
  const select = (chosen, focus) => {
    for (const button of buttons) {
      const on = button === chosen;
      button.setAttribute("aria-selected", String(on));
      button.tabIndex = on ? 0 : -1;
      document.getElementById(button.getAttribute("aria-controls")).hidden = !on;
    }
    if (focus) chosen.focus();
  };
  buttons.forEach((button, index) => {
    button.addEventListener("click", () => select(button, false));
    button.addEventListener("keydown", (event) => {
      const moves = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 };
      let next = null;
      if (event.key in moves) next = (index + moves[event.key] + buttons.length) % buttons.length;
      if (event.key === "Home") next = 0;
      if (event.key === "End") next = buttons.length - 1;
      if (next !== null) {
        event.preventDefault();
        select(buttons[next], true);
      }
    });
  });
}

// Gallery: open a picture large, then step through with the buttons or arrows.
const lightbox = document.getElementById("lightbox");
if (lightbox) {
  const shots = [...document.querySelectorAll("[data-shot]")];
  const picture = lightbox.querySelector("img");
  const caption = lightbox.querySelector("figcaption");
  let current = 0;
  const show = (index) => {
    current = (index + shots.length) % shots.length;
    const image = shots[current].querySelector("img");
    picture.src = image.src;
    picture.alt = image.alt;
    caption.textContent = image.alt;
  };
  shots.forEach((shot, index) => {
    shot.addEventListener("click", () => {
      show(index);
      lightbox.showModal();
    });
  });
  lightbox.querySelector("[data-prev]").addEventListener("click", () => show(current - 1));
  lightbox.querySelector("[data-next]").addEventListener("click", () => show(current + 1));
  lightbox.querySelector("[data-close]").addEventListener("click", () => lightbox.close());
  lightbox.addEventListener("keydown", (event) => {
    if (event.key === "ArrowLeft") show(current - 1);
    if (event.key === "ArrowRight") show(current + 1);
  });
  lightbox.addEventListener("click", (event) => {
    if (event.target === lightbox) lightbox.close();
  });
}

"""
    + FORM_JS
    + """
// Fade sections in as they scroll into view (skipped for reduced motion).
const reveals = document.querySelectorAll(".reveal");
if ("IntersectionObserver" in window && !matchMedia("(prefers-reduced-motion: reduce)").matches) {
  const watcher = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) {
          entry.target.classList.add("in");
          watcher.unobserve(entry.target);
        }
      }
    },
    { rootMargin: "0px 0px -8% 0px" }
  );
  reveals.forEach((item) => watcher.observe(item));
} else {
  reveals.forEach((item) => item.classList.add("in"));
}
"""
)

_README = """# $title

A multi-page website with no build step. Open `index.html` in a browser, or
use the Studio preview.

- Pages: `index.html`, `about.html`, `services.html` (tabs with prices),
  `gallery.html` (tap a picture to open it large), `contact.html` (form,
  hours, map link). Every page shares the same header and footer.
- `styles.css`: colours, fonts, and sizes are variables at the top.
- `app.js`: header and phone menu, tabs, picture viewer, form checks,
  and the fade-in as you scroll.
- `images/`: replace the drawn placeholders with real photos, and
  credit them in the footer.
- The contact form: with the business's email in the form's `data-email`,
  a visitor's message opens in their email app, addressed to the business.
  To get messages without that step, sign up to a form service such as
  Formspree and put its address in the form's `data-endpoint`.

## Put it online (free)

It is plain files, so any static host works:

- **Netlify Drop**: open app.netlify.com/drop and drag this folder onto it.
- **Cloudflare Pages**: Create a project, choose *Direct Upload*, and upload
  this folder.
- **GitHub Pages**: put the files in a repository and turn on Pages in its
  settings.

Each gives a free web address; connect the business's own domain in the
host's domain settings.
"""

BUSINESS = {
    "index.html": _HOME,
    "about.html": _ABOUT,
    "services.html": _SERVICES,
    "gallery.html": _GALLERY,
    "contact.html": _CONTACT,
    "styles.css": _STYLES,
    "app.js": _SCRIPT,
    "images/hero.svg": _art("#2e1b10", "#7e431d", "#d99a5b"),
    "images/photo-1.svg": _art("#2a1a14", "#6d3b2a", "#c98f6b"),
    "images/photo-2.svg": _art("#1d1b16", "#5a4a2c", "#c7a86a"),
    "images/photo-3.svg": _art("#231812", "#8a4b2a", "#e0b184"),
    "README.md": _README,
}
