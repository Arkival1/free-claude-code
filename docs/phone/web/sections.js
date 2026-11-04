// FCC Web kit sections: ready-made, polished sections for a website (FCC's
// own markup on web/kit.css), looks (a brand colour, an accent, a theme and a
// font pair), and the page that puts them together. The AI picks sections
// for the site's goal, then writes the real words and swaps the gradient art
// for real photos. FCCNAME stands for the site's name.

const svg = (path) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${path}</svg>`;

export const ICONS = {
  spark: svg('<path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M6 18l2.5-2.5M15.5 8.5 18 6"/>'),
  shield: svg('<path d="M12 3 5 6v6c0 4.2 3 7.4 7 9 4-1.6 7-4.8 7-9V6z"/><path d="m9 12 2 2 4-4"/>'),
  bolt: svg('<path d="M13 2 4 14h7l-1 8 9-12h-7z"/>'),
  heart: svg('<path d="M12 20s-7-4.4-9-9a5 5 0 0 1 9-3 5 5 0 0 1 9 3c-2 4.6-9 9-9 9z"/>'),
  clock: svg('<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>'),
  leaf: svg('<path d="M5 19c8 0 14-6 14-15-9 0-15 6-15 14"/><path d="M5 19 14 10"/>'),
  chart: svg('<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>'),
  chat: svg('<path d="M4 5h16v11H9l-5 4z"/>'),
  globe: svg('<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3.2 3 14.8 0 18M12 3c-3 3.2-3 14.8 0 18"/>'),
  star: svg('<path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1 6.2L12 17.3 6.5 20.2l1-6.2L3 9.6l6.2-.9z"/>'),
  cup: svg('<path d="M4 8h13v5a6 6 0 0 1-6 6H10a6 6 0 0 1-6-6z"/><path d="M17 10h1.5a2.5 2.5 0 0 1 0 5H17M8 3v2M12 3v2"/>'),
  pin: svg('<path d="M12 21s-7-6.2-7-11a7 7 0 0 1 14 0c0 4.8-7 11-7 11z"/><circle cx="12" cy="10" r="2.5"/>'),
};

const menuIcon = svg('<path d="M4 7h16M4 12h16M4 17h16"/>');
const moon = svg('<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>');

/** Font pairs: a heading face and a body face (Google Fonts when online,
 *  good system faces when not). */
export const FONTS = {
  modern: { name: "Modern", head: '"Inter Tight", "Inter", system-ui, sans-serif', body: '"Inter", system-ui, sans-serif', families: ["Inter+Tight:wght@600;700;800", "Inter:wght@400;500;600"] },
  editorial: { name: "Editorial", head: '"Fraunces", "Iowan Old Style", Georgia, serif', body: '"Inter", system-ui, sans-serif', families: ["Fraunces:opsz,wght@9..144,600;9..144,700", "Inter:wght@400;500;600"] },
  warm: { name: "Warm", head: '"DM Serif Display", Georgia, serif', body: '"DM Sans", system-ui, sans-serif', families: ["DM+Serif+Display", "DM+Sans:wght@400;500;700"] },
  tech: { name: "Tech", head: '"Space Grotesk", system-ui, sans-serif', body: '"Inter", system-ui, sans-serif', families: ["Space+Grotesk:wght@500;700", "Inter:wght@400;500;600"] },
  friendly: { name: "Friendly", head: '"Nunito", ui-rounded, system-ui, sans-serif', body: '"Nunito", ui-rounded, system-ui, sans-serif', families: ["Nunito:wght@400;600;800"] },
  luxury: { name: "Luxury", head: '"Cormorant Garamond", Georgia, serif', body: '"Montserrat", system-ui, sans-serif', families: ["Cormorant+Garamond:wght@500;700", "Montserrat:wght@400;500;600"] },
  bold: { name: "Bold", head: '"Archivo Black", "Arial Black", system-ui, sans-serif', body: '"Archivo", system-ui, sans-serif', families: ["Archivo+Black", "Archivo:wght@400;500;700"] },
};

/** Looks: a brand colour, an accent, light or dark, and a font pair. */
export const LOOKS = {
  ocean: { name: "Ocean", brand: "#2563eb", accent: "#06b6d4", theme: "light", fonts: "modern" },
  forest: { name: "Forest", brand: "#166534", accent: "#ca8a04", theme: "light", fonts: "editorial" },
  espresso: { name: "Espresso", brand: "#7c4a2d", accent: "#d4a373", theme: "light", fonts: "warm" },
  sunset: { name: "Sunset", brand: "#ea580c", accent: "#db2777", theme: "light", fonts: "friendly" },
  midnight: { name: "Midnight", brand: "#6366f1", accent: "#22d3ee", theme: "dark", fonts: "tech" },
  rose: { name: "Rose", brand: "#be185d", accent: "#f59e0b", theme: "light", fonts: "luxury" },
  mono: { name: "Mono", brand: "#111111", accent: "#ff4d00", theme: "light", fonts: "bold" },
  mint: { name: "Mint", brand: "#047857", accent: "#0ea5e9", theme: "light", fonts: "modern" },
};

const navLinks = ["About", "Services", "Pricing", "Contact"].map((name) => `<li><a href="#${name.toLowerCase()}">${name}</a></li>`).join("");
const panelLinks = ["About", "Services", "Pricing", "Contact"].map((name) => `<a href="#${name.toLowerCase()}">${name}</a>`).join("");
const toggle = `<button class="nav-toggle" type="button" aria-expanded="false" aria-label="Menu">${menuIcon}</button>`;
const themeButton = `<button class="btn btn-ghost" type="button" data-theme-toggle aria-label="Light or dark">${moon}</button>`;
const card = (icon, title, text) => `<article class="card" data-reveal><div class="icon">${ICONS[icon]}</div><h3>${title}</h3><p class="muted">${text}</p></article>`;
const quote = (text, name, role) => `<figure class="card quote" data-reveal><div class="stars" aria-label="5 stars">★★★★★</div><blockquote>“${text}”</blockquote><figcaption><span class="avatar" aria-hidden="true"></span><span><strong>${name}</strong>${role}</span></figcaption></figure>`;

/** The sections: group, name, what it's for, and its markup. */
export const SECTIONS = {
  "nav-simple": {
    group: "Navigation",
    name: "Menu bar",
    about: "Logo left, links right, a button; a phone menu under the toggle.",
    html: `<header class="nav"><div class="wrap nav-inner"><a class="logo" href="#top"><span class="logo-mark" aria-hidden="true">✦</span>FCCNAME</a><ul class="nav-links">${navLinks}</ul><a class="btn nav-cta" href="#contact">Get in touch</a>${toggle}</div><nav class="wrap nav-panel" aria-label="Menu">${panelLinks}</nav></header>`,
  },
  "nav-centered": {
    group: "Navigation",
    name: "Centred menu",
    about: "Links in the middle, the logo left, a theme switch and button right.",
    html: `<header class="nav nav-centered"><div class="wrap nav-inner"><a class="logo" href="#top"><span class="logo-mark" aria-hidden="true">✦</span>FCCNAME</a><ul class="nav-links">${navLinks}</ul><div class="cluster nav-cta">${themeButton}<a class="btn" href="#contact">Book now</a></div>${toggle}</div><nav class="wrap nav-panel" aria-label="Menu">${panelLinks}</nav></header>`,
  },
  "hero-split": {
    group: "Hero",
    name: "Split hero",
    about: "Headline, line and two buttons beside a big picture; trust line under.",
    html: `<section class="hero" id="top"><div class="wrap split"><div data-reveal><span class="badge badge-dot">New this season</span><h1>Make something people remember</h1><p class="lead">FCCNAME helps you do the one thing that matters, beautifully, without the busywork.</p><div class="cluster"><a class="btn btn-arrow" href="#pricing">Get started</a><a class="btn btn-ghost" href="#about">See how it works</a></div><div class="trust"><span class="faces" aria-hidden="true"><span></span><span></span><span></span></span><span><span class="stars">★★★★★</span> Loved by 2,000+ customers</span></div></div><div class="art" role="img" aria-label="Picture of FCCNAME" data-reveal></div></div></section>`,
  },
  "hero-center": {
    group: "Hero",
    name: "Centred hero",
    about: "A big centred headline, two buttons and a wide picture below.",
    html: `<section class="hero hero-center" id="top"><div class="wrap"><div class="wrap-narrow" data-reveal><span class="eyebrow">FCCNAME</span><h1>The simplest way to get it done</h1><p class="lead">One clear promise in a sentence or two: who it's for and what changes for them.</p><div class="cluster"><a class="btn btn-arrow" href="#pricing">Start free</a><a class="btn btn-ghost" href="#about">Learn more</a></div></div><div class="art art-2" role="img" aria-label="Picture of FCCNAME" data-reveal></div></div></section>`,
  },
  "hero-image": {
    group: "Hero",
    name: "Photo hero",
    about: "A full-screen photo with the headline over it (cafés, venues, travel).",
    html: `<section class="hero hero-image" id="top"><div class="art art-2" role="img" aria-label="Photo of FCCNAME"></div><div class="wrap"><span class="eyebrow">Since 2014</span><h1>Fresh every morning, right on your corner</h1><p class="lead">Say what makes this place worth the trip, in one warm sentence.</p><div class="cluster"><a class="btn btn-light btn-arrow" href="#menu">See the menu</a><a class="btn btn-ghost" style="color:#fff;border-color:rgb(255 255 255 / .4)" href="#contact">Find us</a></div></div></section>`,
  },
  "hero-bento": {
    group: "Hero",
    name: "Bento hero",
    about: "A headline over a grid of tiles: a big feature, numbers and pictures.",
    html: `<section class="hero" id="top"><div class="wrap"><div class="head" data-reveal><span class="eyebrow">FCCNAME</span><h1>Everything you need, in one place</h1><p class="lead">A short line that sums up the offer.</p></div><div class="bento"><article class="card card-feature" data-reveal><span class="big-number">3×</span><h3>Faster than doing it by hand</h3><p class="muted">The biggest benefit, with a number.</p></article><article class="card" data-reveal><div class="icon">${ICONS.bolt}</div><h3>Quick to start</h3></article><article class="card" data-reveal><div class="icon">${ICONS.shield}</div><h3>Safe by default</h3></article><div class="art" role="img" aria-label="Picture" style="--ratio:auto" data-reveal></div><article class="card" data-reveal><h3>Trusted by teams</h3><p class="muted">“The one tool we never switch off.”</p></article></div></div></section>`,
  },
  logos: {
    group: "Proof",
    name: "Logo strip",
    about: "Names of clients or press, quietly, under the hero.",
    html: `<section class="section-tight"><div class="wrap"><p class="small muted" style="text-align:center">Trusted by people at</p><div class="logos" data-reveal><span>Northwind</span><span>Lumen</span><span>Atlas&amp;Co</span><span>Kettle</span><span>Ridge</span></div></div></section>`,
  },
  stats: {
    group: "Proof",
    name: "Numbers",
    about: "Three or four big numbers that prove it works.",
    html: `<section class="section section-sunken"><div class="wrap"><div class="stats"><div data-reveal><strong>12k+</strong><span class="muted">happy customers</span></div><div data-reveal><strong>4.9★</strong><span class="muted">average review</span></div><div data-reveal><strong>24h</strong><span class="muted">turnaround</span></div><div data-reveal><strong>10 yrs</strong><span class="muted">of craft</span></div></div></div></section>`,
  },
  testimonials: {
    group: "Proof",
    name: "Reviews",
    about: "Three short reviews with names.",
    html: `<section class="section" id="reviews"><div class="wrap"><div class="head head-center" data-reveal><span class="eyebrow">Reviews</span><h2>People love FCCNAME</h2></div><div class="grid">${quote("It changed how we work. Simple, fast and it just looks right.", "Maya Chen", "Owner, Lumen Studio")}${quote("The best decision we made this year. The team noticed on day one.", "Sam Okafor", "Manager, Ridge")}${quote("Friendly, quick and worth every cent. I tell everyone about it.", "Lucia Romero", "Customer since 2021")}</div></div></section>`,
  },
  "quote-big": {
    group: "Proof",
    name: "Big quote",
    about: "One strong review, large, on its own.",
    html: `<section class="section section-ink"><div class="wrap-narrow"><figure class="quote quote-big" data-reveal><blockquote>“FCCNAME is the rare thing that does exactly what it says, and does it beautifully.”</blockquote><figcaption><span class="avatar" aria-hidden="true"></span><span><strong>Jordan Ellis</strong>Editor, The Weekly</span></figcaption></figure></div></section>`,
  },
  "features-grid": {
    group: "Features",
    name: "Feature cards",
    about: "Six benefits as icon cards (services, reasons to choose you).",
    html: `<section class="section" id="services"><div class="wrap"><div class="head" data-reveal><span class="eyebrow">What you get</span><h2>Built around what you need</h2><p class="lead">Turn features into benefits: say what each one does for the reader.</p></div><div class="grid">${card("bolt", "Fast", "Up and running in minutes, not weeks.")}${card("shield", "Reliable", "It works every time, so you can stop checking.")}${card("heart", "Made with care", "Every detail considered, nothing left rough.")}${card("chat", "Real support", "Talk to a person who knows the answer.")}${card("chart", "Clear results", "See what changed, in plain numbers.")}${card("globe", "Anywhere", "On your phone, your laptop, or in person.")}</div></div></section>`,
  },
  "features-rows": {
    group: "Features",
    name: "Feature rows",
    about: "Two rows of picture + text, alternating sides, with checklists.",
    html: `<section class="section" id="about"><div class="wrap feature-rows"><div class="split" data-reveal><div><span class="eyebrow">How it works</span><h2>Start in three taps</h2><p class="lead">Explain the first step and why it's easy.</p><ul class="checks"><li>No set-up or training</li><li>Works with what you already use</li><li>Cancel any time</li></ul></div><div class="art" role="img" aria-label="Picture"></div></div><div class="split split-flip" data-reveal><div><span class="eyebrow">Then</span><h2>Watch it grow</h2><p class="lead">The second big benefit, told as a story.</p><ul class="checks"><li>Reports every week</li><li>Tips that fit your goals</li></ul></div><div class="art art-2" role="img" aria-label="Picture"></div></div></div></section>`,
  },
  bento: {
    group: "Features",
    name: "Bento grid",
    about: "A mosaic of tiles of different sizes (product features, highlights).",
    html: `<section class="section"><div class="wrap"><div class="head" data-reveal><span class="eyebrow">Highlights</span><h2>Small details, big difference</h2></div><div class="bento"><article class="card card-feature" data-reveal><h3>The headline feature</h3><p class="muted">Give the best thing the biggest tile and a short story.</p></article><article class="card" data-reveal><div class="icon">${ICONS.clock}</div><h3>Saves hours</h3></article><article class="card" data-reveal><div class="icon">${ICONS.leaf}</div><h3>Kind to the planet</h3></article><article class="card" data-reveal><span class="big-number">99%</span><p class="muted">on-time, every month</p></article><div class="art art-3" role="img" aria-label="Picture" style="--ratio:auto" data-reveal></div></div></div></section>`,
  },
  steps: {
    group: "Features",
    name: "Steps",
    about: "Three numbered steps (how it works, how to book).",
    html: `<section class="section section-sunken"><div class="wrap"><div class="head head-center" data-reveal><span class="eyebrow">How it works</span><h2>Three simple steps</h2></div><div class="grid steps"><article class="card" data-reveal><h3>Tell us what you need</h3><p class="muted">A two-minute form, no jargon.</p></article><article class="card" data-reveal><h3>We get to work</h3><p class="muted">You see progress as it happens.</p></article><article class="card" data-reveal><h3>Enjoy the result</h3><p class="muted">Delivered on time, guaranteed.</p></article></div></div></section>`,
  },
  pricing: {
    group: "Offer",
    name: "Pricing",
    about: "Three plans, the middle one marked most popular.",
    html: `<section class="section" id="pricing"><div class="wrap"><div class="head head-center" data-reveal><span class="eyebrow">Pricing</span><h2>Simple, honest prices</h2><p class="lead">No hidden fees. Change or cancel any time.</p></div><div class="pricing"><article class="card plan" data-reveal><h3>Starter</h3><p class="price">$9<small>/month</small></p><p class="muted">For trying it out.</p><ul class="checks"><li>The essentials</li><li>Email support</li></ul><a class="btn btn-ghost" href="#contact">Choose Starter</a></article><article class="card plan plan-pop" data-flag="Most popular" data-reveal><h3>Pro</h3><p class="price">$29<small>/month</small></p><p class="muted">For most people.</p><ul class="checks"><li>Everything in Starter</li><li>Priority support</li><li>Monthly review</li></ul><a class="btn btn-arrow" href="#contact">Choose Pro</a></article><article class="card plan" data-reveal><h3>Team</h3><p class="price">$79<small>/month</small></p><p class="muted">For growing teams.</p><ul class="checks"><li>Everything in Pro</li><li>Up to 10 people</li></ul><a class="btn btn-ghost" href="#contact">Talk to us</a></article></div></div></section>`,
  },
  menu: {
    group: "Offer",
    name: "Menu / price list",
    about: "Items with prices and a line each (cafés, salons, trades).",
    html: `<section class="section" id="menu"><div class="wrap split"><div data-reveal><span class="eyebrow">Menu</span><h2>Made fresh, daily</h2><p class="lead">A line about where the food comes from.</p><div class="art" role="img" aria-label="Photo of the food"></div></div><ul class="menu-list" data-reveal><li><strong>Flat white</strong><span class="price">$4.50</span><p>Double ristretto, silky milk.</p></li><li><strong>Sourdough toast</strong><span class="price">$9</span><p>House loaf, cultured butter, sea salt.</p></li><li><strong>Big breakfast</strong><span class="price">$22</span><p>Eggs your way, mushrooms, greens, bacon.</p></li><li><strong>Seasonal tart</strong><span class="price">$7</span><p>Ask what came out of the oven today.</p></li></ul></div></section>`,
  },
  products: {
    group: "Offer",
    name: "Products",
    about: "A grid of products with prices (a shop).",
    html: `<section class="section" id="shop"><div class="wrap"><div class="head" data-reveal><span class="eyebrow">Shop</span><h2>Bestsellers</h2></div><div class="grid" style="--min:200px">${["Classic", "Signature", "Limited", "Gift set"].map((name, i) => `<article class="product" data-reveal><div class="art${i % 3 ? ` art-${(i % 3) + 1}` : ""}" role="img" aria-label="${name}"></div><h3>${name}</h3><p class="price">$${[24, 38, 56, 72][i]}</p><a class="btn btn-ghost" href="#contact">Add to bag</a></article>`).join("")}</div></div></section>`,
  },
  gallery: {
    group: "Content",
    name: "Gallery",
    about: "A masonry of pictures that open big when tapped.",
    html: `<section class="section" id="gallery"><div class="wrap"><div class="head" data-reveal><span class="eyebrow">Gallery</span><h2>A look inside</h2></div><div class="gallery">${[1, 2, 3, 1, 3, 2].map((n) => `<div class="art${n > 1 ? ` art-${n}` : ""}" role="img" aria-label="Picture" data-reveal></div>`).join("")}</div></div></section>`,
  },
  team: {
    group: "Content",
    name: "Team",
    about: "People with photos, names and roles.",
    html: `<section class="section"><div class="wrap"><div class="head" data-reveal><span class="eyebrow">Team</span><h2>The people behind FCCNAME</h2></div><div class="grid" style="--min:200px">${[["Ava Park", "Founder"], ["Leo Grant", "Lead designer"], ["Nia Brooks", "Customer care"], ["Omar Haddad", "Operations"]].map(([name, role], i) => `<article class="person" data-reveal><div class="art${i % 3 ? ` art-${(i % 3) + 1}` : ""}" role="img" aria-label="${name}"></div><h3>${name}</h3><p class="muted">${role}</p></article>`).join("")}</div></div></section>`,
  },
  timeline: {
    group: "Content",
    name: "Story timeline",
    about: "The story so far, year by year.",
    html: `<section class="section section-sunken"><div class="wrap-narrow"><div class="head" data-reveal><span class="eyebrow">Our story</span><h2>How we got here</h2></div><ol class="timeline"><li data-reveal><time>2014</time><h3>A small idea</h3><p class="muted">Where it started.</p></li><li data-reveal><time>2019</time><h3>Our first home</h3><p class="muted">The moment it became real.</p></li><li data-reveal><time>Today</time><h3>Still growing</h3><p class="muted">What's next.</p></li></ol></div></section>`,
  },
  posts: {
    group: "Content",
    name: "Blog cards",
    about: "Three recent posts or news items.",
    html: `<section class="section"><div class="wrap"><div class="head" data-reveal><span class="eyebrow">Journal</span><h2>Latest news</h2></div><div class="grid">${["How we choose our suppliers", "Five tips for getting started", "What's new this month"].map((title, i) => `<article class="post" data-reveal><div class="art${i ? ` art-${i + 1}` : ""}" role="img" aria-label="${title}"></div><p class="small muted">${["12 May", "3 May", "28 Apr"][i]} · 4 min read</p><h3><a href="#">${title}</a></h3></article>`).join("")}</div></div></section>`,
  },
  faq: {
    group: "Content",
    name: "Questions",
    about: "Common questions that open when tapped.",
    html: `<section class="section" id="faq"><div class="wrap-narrow"><div class="head head-center" data-reveal><span class="eyebrow">FAQ</span><h2>Questions, answered</h2></div><div class="faq">${[["How long does it take?", "Most people are set up the same day."], ["Can I cancel any time?", "Yes, with one tap and no fee."], ["Do you offer refunds?", "If it isn't right in 30 days, we refund you in full."], ["Where are you based?", "Say where, and who you serve."]].map(([question, answer]) => `<details data-reveal><summary>${question}</summary><p>${answer}</p></details>`).join("")}</div></div></section>`,
  },
  "about-split": {
    group: "Content",
    name: "About",
    about: "A short story with a picture and two numbers.",
    html: `<section class="section" id="about"><div class="wrap split"><div class="art art-2" role="img" aria-label="Photo of FCCNAME" data-reveal></div><div data-reveal><span class="eyebrow">About FCCNAME</span><h2>Small team, big care</h2><p class="lead">Tell the story in three sentences: why you started, what you believe, who you do it for.</p><div class="stats" style="text-align:left"><div><strong>10+</strong><span class="muted">years</span></div><div><strong>5k</strong><span class="muted">customers</span></div></div></div></div></section>`,
  },
  "cta-band": {
    group: "Action",
    name: "Call to action",
    about: "A bold band that asks for the one action that matters.",
    html: `<section class="section"><div class="wrap"><div class="cta-band" data-reveal><h2>Ready when you are</h2><p class="lead">One line that removes the last doubt.</p><div class="cluster"><a class="btn btn-light btn-arrow" href="#contact">Get started</a></div></div></div></section>`,
  },
  newsletter: {
    group: "Action",
    name: "Newsletter",
    about: "An email sign-up in one line.",
    html: `<section class="section section-sunken"><div class="wrap-narrow head-center" style="text-align:center" data-reveal><h2>Get the good stuff first</h2><p class="lead">One email a month. No spam, ever.</p><form class="inline-form" data-thanks="You're on the list. Welcome!"><input type="email" required placeholder="you@example.com" autocomplete="email" aria-label="Email address" /><button class="btn" type="submit">Subscribe</button></form></div></section>`,
  },
  contact: {
    group: "Action",
    name: "Contact",
    about: "A form beside the address, hours, phone and email.",
    html: `<section class="section" id="contact"><div class="wrap split"><div data-reveal><span class="eyebrow">Contact</span><h2>Let's talk</h2><p class="lead">We usually reply within a day.</p><dl class="info"><div><dt>Visit</dt><dd>12 Harbour Street, Sydney</dd></div><div><dt>Hours</dt><dd>Mon–Fri 7am–4pm · Sat 8am–2pm</dd></div><div><dt>Call</dt><dd><a href="tel:+61200000000">(02) 0000 0000</a></dd></div><div><dt>Email</dt><dd><a href="mailto:hello@example.com">hello@example.com</a></dd></div></dl></div><form class="card form" data-thanks="Thanks! We'll get back to you within a day." data-reveal><label class="field">Name<input name="name" required autocomplete="name" /></label><label class="field">Email<input name="email" type="email" required autocomplete="email" /></label><label class="field">Message<textarea name="message" required></textarea></label><button class="btn btn-arrow" type="submit">Send message</button></form></div></section>`,
  },
  "footer-columns": {
    group: "Footer",
    name: "Footer with columns",
    about: "Logo and line, link columns, and the small print.",
    html: `<footer class="footer"><div class="wrap"><div class="footer-grid"><div><a class="logo" href="#top"><span class="logo-mark" aria-hidden="true">✦</span>FCCNAME</a><p style="margin-top:12px">A one-line promise.</p></div><div><h4>Explore</h4><ul><li><a href="#about">About</a></li><li><a href="#services">Services</a></li><li><a href="#pricing">Pricing</a></li></ul></div><div><h4>Help</h4><ul><li><a href="#faq">FAQ</a></li><li><a href="#contact">Contact</a></li></ul></div><div><h4>Follow</h4><ul><li><a href="#">Instagram</a></li><li><a href="#">LinkedIn</a></li></ul></div></div><div class="footer-base"><span>© <span data-year></span> FCCNAME</span><span>Made with care</span></div></div></footer>`,
  },
  "footer-simple": {
    group: "Footer",
    name: "Simple footer",
    about: "One line: the name, a few links and the year.",
    html: `<footer class="footer"><div class="wrap footer-base" style="margin-top:0;border-top:0;padding-top:0"><a class="logo" href="#top"><span class="logo-mark" aria-hidden="true">✦</span>FCCNAME</a><span class="cluster"><a href="#about">About</a><a href="#contact">Contact</a></span><span>© <span data-year></span></span></div></footer>`,
  },
};

/** The kit's sample lines: a finished site has replaced every one (the
 *  project check lists any that are left). */
export const SAMPLE_TEXT = [
  "Make something people remember",
  "helps you do the one thing that matters",
  "The simplest way to get it done",
  "One clear promise in a sentence or two",
  "Fresh every morning, right on your corner",
  "Say what makes this place worth the trip",
  "Everything you need, in one place",
  "A short line that sums up the offer",
  "The biggest benefit, with a number",
  "Northwind",
  "Turn features into benefits",
  "Explain the first step and why it's easy",
  "The second big benefit, told as a story",
  "Give the best thing the biggest tile",
  "A line about where the food comes from",
  "Maya Chen",
  "Sam Okafor",
  "Jordan Ellis",
  "Ava Park",
  "Tell the story in three sentences",
  "How we choose our suppliers",
  "Say where, and who you serve.",
  "One line that removes the last doubt.",
  "12 Harbour Street, Sydney",
  "(02) 0000 0000",
  "A one-line promise.",
];

/** Ready-made section lists for common sites. */
export const RECIPES = {
  business: { name: "Local business", look: "espresso", sections: ["nav-simple", "hero-image", "logos", "about-split", "menu", "testimonials", "gallery", "faq", "contact", "footer-columns"] },
  startup: { name: "Product launch", look: "midnight", sections: ["nav-centered", "hero-center", "logos", "bento", "features-rows", "stats", "testimonials", "pricing", "faq", "cta-band", "footer-columns"] },
  studio: { name: "Portfolio / studio", look: "mono", sections: ["nav-simple", "hero-split", "gallery", "quote-big", "steps", "team", "contact", "footer-simple"] },
  shop: { name: "Shop", look: "rose", sections: ["nav-centered", "hero-bento", "products", "features-grid", "testimonials", "newsletter", "footer-columns"] },
  service: { name: "Services / trades", look: "ocean", sections: ["nav-simple", "hero-split", "stats", "features-grid", "steps", "pricing", "testimonials", "faq", "contact", "footer-columns"] },
};

const escape = (text) => String(text).replace(/[&<>"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[char]);

/** The site's own styles.css: its look on top of the kit. */
export function lookCss(lookId = "ocean", fontsId = "") {
  const look = LOOKS[lookId] || LOOKS.ocean;
  const fonts = FONTS[fontsId] || FONTS[look.fonts];
  return `/* This site's look (on the FCC Web kit, kit/kit.css). Change the brand
   colour, the accent or the fonts here and the whole site follows. */
:root {
  --brand: ${look.brand};
  --accent: ${look.accent};
  --font-head: ${fonts.head};
  --font-body: ${fonts.body};
}

/* Your own styles go below. */
`;
}

/** A whole page from sections, in a look. */
export function pageHtml({ title = "My site", description = "", sections = RECIPES.business.sections, look = "ocean", fonts = "" } = {}) {
  const chosen = LOOKS[look] || LOOKS.ocean;
  const pair = FONTS[fonts] || FONTS[chosen.fonts];
  const name = escape(title);
  // The menu bar goes before <main> and the footer after it.
  const part = (group, wanted) =>
    sections
      .filter((id) => SECTIONS[id] && (SECTIONS[id].group === group) === wanted)
      .map((id) => SECTIONS[id].html)
      .join("\n")
      .replaceAll("FCCNAME", name);
  const navs = part("Navigation", true);
  const footers = part("Footer", true);
  const body = sections
    .filter((id) => SECTIONS[id] && !["Navigation", "Footer"].includes(SECTIONS[id].group))
    .map((id) => SECTIONS[id].html)
    .join("\n")
    .replaceAll("FCCNAME", name);
  const fontLink = pair.families.length ? `\n  <link rel="preconnect" href="https://fonts.googleapis.com" />\n  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />\n  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?${pair.families.map((family) => `family=${family}`).join("&")}&display=swap" />` : "";
  return `<!doctype html>
<html lang="en" data-theme="${chosen.theme}">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
  <title>${name}</title>
  <meta name="description" content="${escape(description || `${title}: say what it is and who it's for in one line.`)}" />
  <meta name="theme-color" content="${chosen.brand}" />
  <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>✦</text></svg>" />${fontLink}
  <link rel="stylesheet" href="kit/kit.css" />
  <link rel="stylesheet" href="styles.css" />
</head>
<body>
<a class="skip" href="#main">Skip to content</a>
${navs}
<main id="main">
${body}
</main>
${footers}
<script src="kit/kit.js" defer></script>
</body>
</html>
`;
}
