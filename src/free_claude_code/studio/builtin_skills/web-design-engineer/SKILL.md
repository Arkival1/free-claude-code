---
name: web-design-engineer
description: How to design and build a website that looks professionally designed and works on every screen - a design system first, then layout, type, colour, components, motion, accessibility, speed and real content, checked before finishing.
---

# Website design engineer

Work in this order. Each step has a rule you can check.

1. **Direction.** Say in one line who the site is for, the one action a
   visitor should take (the main button), and the mood (calm, bold,
   premium, playful, technical). Every later choice follows it.
2. **Design system in `:root` first.** Colours: `--bg`, `--surface`,
   `--text`, `--muted`, `--primary`, `--on-primary`, `--accent`,
   `--border`; body text on background at least 4.5:1 contrast. Two fonts
   at most (a Google Font pair, `display=swap`). Type scale with `clamp()`
   (e.g. h1 `clamp(2.2rem, 5vw, 3.6rem)`, body 1rem-1.125rem), text
   line-height 1.5-1.7, headings 1.1-1.25. Spacing scale (4, 8, 12, 16, 24,
   32, 48, 64, 96px), one radius, one or two shadows, a container of
   1100-1200px max-width with side padding.
3. **Layout, phone first.** Sections share a vertical rhythm (padding
   `clamp(3rem, 8vw, 6rem)`). Cards use `grid` with
   `repeat(auto-fit, minmax(16rem, 1fr))`; rows use flex with gap. Add
   `@media` breakpoints around 640px and 960px. No sideways scrolling at
   360px wide. A sticky header with a phone menu button
   (`aria-expanded`, closes on link click).
4. **Page structure.** `header`, `nav`, `main`, `footer`; exactly one `h1`;
   headings in order (no h1 to h3 jump). A hero with a benefit headline, a
   short line under it, the main button and a second one, and a strong
   picture; then proof (reviews, numbers, logos), what is offered, about,
   FAQ, a closing call to action, and a footer with contact and links.
5. **Components and states.** Buttons: primary and secondary, at least 44px
   tall, with `:hover`, `:focus-visible` (a clear ring), `:active` and
   disabled looks. Links show they are links. Cards share padding, radius
   and shadow. Forms: a `<label>` for every field, helpful errors, a clear
   focus.
6. **Pictures.** Real photos (`list_photos`/`use_photo`, else `find_images`
   and `save_image`), `object-fit: cover` with an `aspect-ratio`, `width`
   and `height`, `loading="lazy"` below the first screen, real alt text.
   Icons as inline SVG in one consistent style.
7. **Motion.** Transitions of 150-250ms on hovers and toggles, gentle
   reveals at most, and a `@media (prefers-reduced-motion: reduce)` rule
   that turns them off.
8. **Accessibility.** `<html lang="en">`, a skip link, landmarks, labels,
   alt text, visible focus, link text that says where it goes (never "click
   here"), and `rel="noopener"` on every `target="_blank"` link.
9. **Speed and sharing.** A `<title>`, `<meta name="description">`, a
   favicon, Open Graph title and image, fonts preconnected, scripts
   `defer`red, images sized so nothing jumps while loading.
10. **Content.** Real, specific words for this business or person: names,
    services, prices, hours, places. No lorem ipsum, no "Your text here",
    no template lines left.
11. **Before finishing.** Run `check_project` and `polish_check` and fix
    everything they report; use the page with `try_page` and see it with
    `look_page` (PC and phone screenshots the Vision Model judges), fix what
    it shows and look again (3 rounds at most); then say what you built and
    how to open it.

**Go deeper when the site needs it** (read one with the `skill` tool, by
name): `design-taste-frontend` (a design direction that doesn't look
templated), `impeccable` (shape, audit, polish, typography, colour, motion;
its guides are in `impeccable/reference/`), `redesign-existing-projects`
(upgrading a site that already exists), a style to match the mood
(`minimalist-ui`, `high-end-visual-design`, `industrial-brutalist-ui`,
`gpt-taste`), and `web-design-guidelines` to check the finished pages.
