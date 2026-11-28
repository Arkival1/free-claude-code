"""Turn a site spec (theme + sections) into one self-contained HTML page.

Every piece of owner or model text is HTML-escaped, links are limited to
http(s), mailto:, tel: and #anchors, and the page needs nothing from the web
(images are optional; without one a tasteful CSS placeholder is drawn).
"""

import html
import re
from collections.abc import Callable
from typing import Any

from .library import FONTS, PALETTES

_SAFE_LINK = re.compile(r"^(https?://|mailto:|tel:|#)[^\s\"'<>]*$", re.IGNORECASE)


def esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def link(value: Any, fallback: str = "#") -> str:
    text = str(value or "").strip()
    return esc(text) if _SAFE_LINK.match(text) else fallback


def image(value: Any) -> str:
    text = str(value or "").strip()
    return esc(text) if re.match(r"^https?://[^\s\"'<>]+$", text, re.IGNORECASE) else ""


def anchor(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-") or "section"


def rows(value: Any) -> list[list[str]]:
    if not isinstance(value, list):
        return []
    return [[str(c) for c in r] if isinstance(r, list) else [str(r)] for r in value]


def _theme_css(
    theme: dict[str, Any],
    palettes: dict[str, dict[str, str]],
    fonts: dict[str, dict[str, Any]],
) -> str:
    pal = theme.get("palette")
    colours = (
        pal if isinstance(pal, dict) else palettes.get(str(pal), PALETTES["Espresso"])
    )
    font = fonts.get(str(theme.get("font")), FONTS["Modern Sans"])
    radius = max(0, min(40, int(theme.get("radius", 14))))
    spacing = max(0.6, min(1.6, float(theme.get("spacing", 1.0))))
    scale = max(0.8, min(1.3, float(theme.get("scale", 1.0))))
    shadow = max(0, min(3, int(theme.get("shadow", 1))))
    width = max(760, min(1440, int(theme.get("width", 1120))))
    shadows = [
        "none",
        "0 1px 3px rgba(0,0,0,.08)",
        "0 8px 24px rgba(0,0,0,.12)",
        "0 18px 48px rgba(0,0,0,.22)",
    ]
    keys = ("bg", "surface", "text", "muted", "primary", "on_primary", "accent")
    css_vars = ";".join(
        f"--{k.replace('_', '-')}:{esc(colours.get(k, '#888888'))}" for k in keys
    )
    return (
        f":root{{{css_vars};--radius:{radius}px;--gap:{round(24 * spacing)}px;--pad:{round(72 * spacing)}px;"
        f"--fs:{round(16 * scale, 1)}px;--shadow:{shadows[shadow]};--width:{width}px;"
        f"--font-h:{font['heading']};--font-b:{font['body']};--hw:{font['weight']};--track:{font['tracking']}}}"
    )


BASE_CSS = """
*{box-sizing:border-box;min-width:0}html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--text);font:var(--fs)/1.6 var(--font-b)}
h1,h2,h3{font-family:var(--font-h);font-weight:var(--hw);letter-spacing:var(--track);line-height:1.1;margin:0 0 .5em}
h1{font-size:clamp(2.1em,5vw,3.6em)}h2{font-size:clamp(1.6em,3.4vw,2.4em)}h3{font-size:1.15em}
p{margin:0 0 1em}a{color:var(--primary)}img{max-width:100%;display:block}
.wrap{max-width:var(--width);margin:0 auto;padding:0 var(--gap)}
.s{padding:var(--pad) 0}.s.alt{background:var(--surface)}
.muted{color:var(--muted)}.eyebrow{color:var(--primary);font-weight:600;letter-spacing:.08em;text-transform:uppercase;font-size:.8em}
.grid{display:grid;gap:var(--gap);grid-template-columns:repeat(auto-fit,minmax(min(100%,240px),1fr))}
.card{background:var(--surface);border-radius:var(--radius);padding:calc(var(--gap)*1.1);box-shadow:var(--shadow);border:1px solid color-mix(in srgb,var(--text) 8%,transparent)}
.btn{display:inline-block;padding:.8em 1.5em;font-weight:600;text-decoration:none;border-radius:var(--radius);transition:transform .2s,box-shadow .2s,background .2s;cursor:pointer;border:2px solid transparent;font-family:inherit;font-size:1em}
.btn.solid{background:var(--primary);color:var(--on-primary)}
.btn.pill{background:var(--primary);color:var(--on-primary);border-radius:999px}
.btn.outline{border-color:var(--primary);color:var(--primary);background:transparent}
.btn.ghost{color:var(--primary);background:transparent}.btn.ghost:hover{background:color-mix(in srgb,var(--primary) 12%,transparent)}
.btn.gradient{background:linear-gradient(120deg,var(--primary),var(--accent));color:var(--on-primary)}
.btn.lifted{background:var(--primary);color:var(--on-primary);box-shadow:0 10px 24px color-mix(in srgb,var(--primary) 45%,transparent)}
.btn.lifted:hover{transform:translateY(-3px)}
.btn.underline{color:var(--primary);padding-left:0;padding-right:0;border-radius:0;background:linear-gradient(var(--primary),var(--primary)) 0 100%/30% 2px no-repeat}
.btn.underline:hover{background-size:100% 2px}
.btn:hover{transform:translateY(-1px)}
.art{border-radius:var(--radius);min-height:280px;background:radial-gradient(circle at 30% 30%,color-mix(in srgb,var(--accent) 70%,transparent),transparent 55%),radial-gradient(circle at 75% 70%,color-mix(in srgb,var(--primary) 75%,transparent),transparent 60%),var(--surface);display:flex;align-items:flex-end;padding:var(--gap);color:var(--text);font-weight:600;box-shadow:var(--shadow);overflow:hidden}
.art img{width:100%;height:100%;object-fit:cover}
nav.top{position:sticky;top:0;z-index:5;background:color-mix(in srgb,var(--bg) 88%,transparent);backdrop-filter:blur(10px);border-bottom:1px solid color-mix(in srgb,var(--text) 8%,transparent)}
nav.top .wrap{display:flex;align-items:center;gap:var(--gap);min-height:64px;flex-wrap:wrap}
nav.top .brand{font-family:var(--font-h);font-weight:var(--hw);font-size:1.25em;text-decoration:none;color:var(--text);margin-right:auto}
nav.top.v-centered .wrap{justify-content:center}nav.top.v-centered .brand{margin-right:0;width:100%;text-align:center;padding-top:12px}
nav.top a.l{color:var(--text);text-decoration:none;opacity:.85}nav.top a.l:hover{opacity:1;color:var(--primary)}
.hero{padding:calc(var(--pad)*1.3) 0}.hero .lead{font-size:1.2em;max-width:38em}
.hero .actions{display:flex;gap:var(--gap);align-items:center;flex-wrap:wrap;margin-top:1.5em}
.hero.v-split .wrap{display:grid;gap:calc(var(--gap)*2);grid-template-columns:1.1fr .9fr;align-items:center}
.hero.v-centered{text-align:center}.hero.v-centered .lead{margin:0 auto}.hero.v-centered .actions{justify-content:center}
.hero.v-bold h1{font-size:clamp(2.6em,7vw,5em)}.hero.v-bold{background:linear-gradient(160deg,color-mix(in srgb,var(--primary) 18%,var(--bg)),var(--bg) 60%)}
.two{display:grid;gap:calc(var(--gap)*2);grid-template-columns:1fr 1fr}
.ticks{list-style:none;padding:0;margin:0}.ticks li{padding:.45em 0 .45em 1.8em;position:relative}
.ticks li:before{content:"";position:absolute;left:0;top:.85em;width:.9em;height:.9em;border-radius:50%;background:var(--primary)}
.menu-sec h3{border-bottom:2px solid var(--primary);padding-bottom:.3em;margin-top:.4em}
.item{display:flex;gap:1em;align-items:baseline;padding:.55em 0;border-bottom:1px dashed color-mix(in srgb,var(--text) 18%,transparent)}
.item .n{font-weight:600}.item .dots{flex:1}.item .p{font-weight:700;white-space:nowrap;color:var(--primary)}
.item small{display:block;color:var(--muted)}
table.hours{border-collapse:collapse;width:100%;max-width:520px}table.hours td{padding:.7em 0;border-bottom:1px solid color-mix(in srgb,var(--text) 12%,transparent)}
table.hours td:last-child{text-align:right;font-weight:600;white-space:nowrap}
.gallery.v-mosaic{grid-template-columns:2fr 1fr 1fr}.gallery.v-mosaic .art:first-child{grid-row:span 2;min-height:420px}
.gallery .art{min-height:200px}
.price{font-size:1.4em;font-weight:700;color:var(--primary);margin:.2em 0 .5em}
.tag{display:inline-block;font-size:.8em;padding:.25em .8em;border-radius:999px;background:color-mix(in srgb,var(--primary) 15%,transparent);color:var(--primary);font-weight:600;margin:0 .4em .4em 0}
.bar{height:10px;border-radius:999px;background:color-mix(in srgb,var(--text) 12%,transparent);overflow:hidden;margin:.4em 0 1.1em}
.bar i{display:block;height:100%;background:linear-gradient(90deg,var(--primary),var(--accent));border-radius:999px}
blockquote{margin:0;font-size:1.05em}blockquote footer{margin-top:.8em;color:var(--muted);font-size:.9em}
.quote-big{font-family:var(--font-h);font-size:clamp(1.4em,3vw,2.1em);line-height:1.3;max-width:28em}
.cta.v-band{background:var(--primary);color:var(--on-primary)}.cta.v-band .btn{background:var(--on-primary);color:var(--primary)}
.cta.v-card .card{text-align:center;padding:calc(var(--gap)*2.2)}
form.contact{display:grid;gap:.8em}form.contact input,form.contact textarea{font:inherit;padding:.8em 1em;border-radius:calc(var(--radius)*.6);border:1px solid color-mix(in srgb,var(--text) 20%,transparent);background:var(--bg);color:var(--text)}
footer.site{padding:calc(var(--pad)*.6) 0;border-top:1px solid color-mix(in srgb,var(--text) 10%,transparent);color:var(--muted)}
footer.site .wrap{display:flex;gap:var(--gap);flex-wrap:wrap;align-items:center}footer.site .wrap span{margin-right:auto}
@media(max-width:760px){.hero.v-split .wrap,.two{grid-template-columns:1fr}.gallery.v-mosaic{grid-template-columns:1fr 1fr}.gallery.v-mosaic .art:first-child{min-height:260px}}
@media(prefers-reduced-motion:reduce){*{transition:none!important;scroll-behavior:auto!important}}
"""


def _btn(style: str, text: str, href: str = "#") -> str:
    if not text:
        return ""
    return f'<a class="btn {esc(style.lower())}" href="{link(href)}">{esc(text)}</a>'


def _art(caption: str, url: str = "") -> str:
    src = image(url)
    inner = (
        f'<img src="{src}" alt="{esc(caption)}" loading="lazy">'
        if src
        else esc(caption)
    )
    return f'<div class="art">{inner}</div>'


def _title(f: dict[str, Any]) -> str:
    return f"<h2>{esc(f.get('title'))}</h2>" if f.get("title") else ""


def nav(f, v, b, ids):
    links = "".join(
        f'<a class="l" href="#{ids.get(anchor(r[0]), "top")}">{esc(r[0])}</a>'
        for r in rows(f.get("links"))
        if r and r[0]
    )
    button = _btn(b, f.get("button", ""), "#" + ids.get("contact", "top"))
    return f'<nav class="top v-{esc(v)}"><div class="wrap"><a class="brand" href="#top">{esc(f.get("brand"))}</a>{links}{button}</div></nav>'


def hero(f, v, b, ids):
    eyebrow = (
        f'<p class="eyebrow">{esc(f.get("eyebrow"))}</p>' if f.get("eyebrow") else ""
    )
    secondary = (
        f'<span class="muted">{esc(f.get("secondary"))}</span>'
        if f.get("secondary")
        else ""
    )
    text = (
        f'<div>{eyebrow}<h1>{esc(f.get("title"))}</h1><p class="lead muted">{esc(f.get("subtitle"))}</p>'
        f'<div class="actions">{_btn(b, f.get("button", ""), f.get("button_link") or "#")}{secondary}</div></div>'
    )
    art = _art(f.get("title", ""), f.get("image_url", "")) if v == "split" else ""
    return f'<header class="hero v-{esc(v)}" id="top"><div class="wrap">{text}{art}</div></header>'


def about(f, v, b, ids):
    points = "".join(
        f"<li>{esc(r[0])}</li>" for r in rows(f.get("points")) if r and r[0]
    )
    ticks = f'<ul class="ticks">{points}</ul>' if points else ""
    if v == "two-column":
        return f'<div class="wrap two"><div>{_title(f)}<p>{esc(f.get("text"))}</p></div><div>{ticks}</div></div>'
    return f'<div class="wrap"><div style="max-width:820px">{_title(f)}<p>{esc(f.get("text"))}</p>{ticks}</div></div>'


def menu(f, v, b, ids):
    groups: dict[str, list[list[str]]] = {}
    for r in rows(f.get("items")):
        r = ([*r, "", "", "", ""])[:4]
        groups.setdefault(r[0] or "Menu", []).append(r)
    blocks = []
    for name, items in groups.items():
        lines = "".join(
            f'<div class="item"><div><span class="n">{esc(i[1])}</span>'
            + (f"<small>{esc(i[3])}</small>" if i[3] else "")
            + f'</div><span class="dots"></span><span class="p">{esc(i[2])}</span></div>'
            for i in items
        )
        cls = "card menu-sec" if v == "cards" else "menu-sec"
        blocks.append(f'<div class="{cls}"><h3>{esc(name)}</h3>{lines}</div>')
    note = (
        f'<p class="muted" style="margin-top:1.5em">{esc(f.get("note"))}</p>'
        if f.get("note")
        else ""
    )
    return f'<div class="wrap">{_title(f)}<div class="grid">{"".join(blocks)}</div>{note}</div>'


def hours(f, v, b, ids):
    trs = "".join(
        f"<tr><td>{esc(r[0])}</td><td>{esc(([*r, ''])[1])}</td></tr>"
        for r in rows(f.get("rows"))
        if r
    )
    note = f'<p class="muted">{esc(f.get("note"))}</p>' if f.get("note") else ""
    return (
        f'<div class="wrap">{_title(f)}<table class="hours">{trs}</table>{note}</div>'
    )


def gallery(f, v, b, ids):
    tiles = "".join(_art(r[0], ([*r, ""])[1]) for r in rows(f.get("items")) if r)
    return f'<div class="wrap">{_title(f)}<div class="grid gallery v-{esc(v)}">{tiles}</div></div>'


def services(f, v, b, ids):
    items = rows(f.get("items"))
    if v == "list":
        lines = "".join(
            f'<div class="item"><div><span class="n">{esc(r[0])}</span><small>{esc(([*r, "", ""])[2])}</small></div>'
            f'<span class="dots"></span><span class="p">{esc(([*r, ""])[1])}</span></div>'
            for r in items
            if r
        )
        return f'<div class="wrap"><div style="max-width:820px">{_title(f)}{lines}</div></div>'
    cards = "".join(
        f'<div class="card"><h3>{esc(r[0])}</h3><div class="price">{esc(([*r, ""])[1])}</div>'
        f'<p class="muted">{esc(([*r, "", ""])[2])}</p></div>'
        for r in items
        if r
    )
    return f'<div class="wrap">{_title(f)}<div class="grid">{cards}</div></div>'


def projects(f, v, b, ids):
    cards = []
    for r in rows(f.get("items")):
        r = ([*r, "", "", "", ""])[:4]
        more = (
            f'<p><a href="{link(r[3])}">View project →</a></p>'
            if r[3] and link(r[3]) != "#"
            else ""
        )
        tag = f'<span class="tag">{esc(r[1])}</span>' if r[1] else ""
        art = _art(r[0]) if v == "grid" else ""
        cards.append(
            f'<div class="card">{art}<div style="padding-top:{"1em" if art else "0"}">{tag}<h3>{esc(r[0])}</h3>'
            f'<p class="muted">{esc(r[2])}</p>{more}</div></div>'
        )
    layout = "grid" if v == "grid" else ""
    return f'<div class="wrap">{_title(f)}<div class="{layout}" style="display:grid;gap:var(--gap)">{"".join(cards)}</div></div>'


def skills(f, v, b, ids):
    items = [([*r, "0"])[:2] for r in rows(f.get("items")) if r]
    if v == "bars":
        body = "".join(
            f'<div>{esc(s)}<div class="bar"><i style="width:{_pct(lvl)}%"></i></div></div>'
            for s, lvl in items
        )
        return f'<div class="wrap"><div style="max-width:720px">{_title(f)}{body}</div></div>'
    return f'<div class="wrap">{_title(f)}<div>{"".join(f"<span class=tag>{esc(s)}</span>" for s, _ in items)}</div></div>'


def _pct(value: str) -> int:
    try:
        return max(0, min(100, int(float(value))))
    except ValueError:
        return 0


def testimonials(f, v, b, ids):
    items = [([*r, ""])[:2] for r in rows(f.get("items")) if r]
    if v == "quote" and items:
        q, n = items[0]
        return f'<div class="wrap">{_title(f)}<blockquote class="quote-big">“{esc(q)}”<footer>{esc(n)}</footer></blockquote></div>'
    cards = "".join(
        f'<blockquote class="card">“{esc(q)}”<footer>{esc(n)}</footer></blockquote>'
        for q, n in items
    )
    return f'<div class="wrap">{_title(f)}<div class="grid">{cards}</div></div>'


def cta(f, v, b, ids):
    inner = f"<h2>{esc(f.get('title'))}</h2><p>{esc(f.get('text'))}</p>{_btn(b, f.get('button', ''), f.get('button_link') or '#contact')}"
    if v == "card":
        return f'<div class="wrap"><div class="card">{inner}</div></div>'
    return f'<div class="wrap" style="text-align:center">{inner}</div>'


def contact(f, v, b, ids):
    details = []
    if f.get("address"):
        details.append(f"<p><b>Address</b><br>{esc(f['address'])}</p>")
    if f.get("phone"):
        details.append(
            f'<p><b>Phone</b><br><a href="tel:{esc(re.sub(r"[^0-9+]", "", str(f["phone"])))}">{esc(f["phone"])}</a></p>'
        )
    if f.get("email"):
        details.append(
            f'<p><b>Email</b><br><a href="mailto:{esc(f["email"])}">{esc(f["email"])}</a></p>'
        )
    form = ""
    if str(f.get("form", "")).strip().lower() in {"yes", "true", "1", "on"}:
        target = esc(f.get("email") or "")
        form = (
            f'<form class="contact" action="mailto:{target}" method="post" enctype="text/plain">'
            '<input name="name" placeholder="Your name" aria-label="Your name">'
            '<input name="email" type="email" placeholder="Your email" aria-label="Your email">'
            '<textarea name="message" rows="4" placeholder="Message" aria-label="Message"></textarea>'
            f'<button class="btn {esc(b.lower())}" type="submit">Send</button></form>'
        )
    text = f'<p class="muted">{esc(f.get("text"))}</p>' if f.get("text") else ""
    if v == "split":
        return f'<div class="wrap two"><div>{_title(f)}{text}{"".join(details)}</div><div>{form}</div></div>'
    return f'<div class="wrap"><div style="max-width:640px">{_title(f)}{text}{"".join(details)}{form}</div></div>'


def footer(f, v, b, ids):
    links = "".join(
        f'<a href="{link(([*r, "#"])[1])}">{esc(r[0])}</a>'
        for r in rows(f.get("links"))
        if r and r[0]
    )
    return f'<footer class="site"><div class="wrap"><span>© {esc(f.get("text"))}</span>{links}</div></footer>'


RENDERERS: dict[str, Callable[..., str]] = {
    "nav": nav,
    "hero": hero,
    "about": about,
    "menu": menu,
    "hours": hours,
    "gallery": gallery,
    "services": services,
    "projects": projects,
    "skills": skills,
    "testimonials": testimonials,
    "cta": cta,
    "contact": contact,
    "footer": footer,
}
_BARE = {"nav", "hero", "footer"}


def render_site(
    spec: dict[str, Any],
    palettes: dict[str, dict[str, str]] | None = None,
    fonts: dict[str, dict[str, Any]] | None = None,
) -> str:
    theme = spec.get("theme") or {}
    button = str(theme.get("button") or "Solid")
    sections = [
        x
        for x in (spec.get("sections") or [])
        if isinstance(x, dict) and x.get("kind") in RENDERERS
    ]
    ids: dict[str, str] = {}
    section_ids: list[str] = []
    used: dict[str, int] = {}
    for section in sections:
        kind = str(section["kind"])
        used[kind] = used.get(kind, 0) + 1
        sec_id = anchor(kind) + (f"-{used[kind]}" if used[kind] > 1 else "")
        section_ids.append(sec_id)
        if kind in _BARE:
            continue
        ids.setdefault(anchor(kind), sec_id)
        title = str((section.get("fields") or {}).get("title") or "")
        for word in [title, *title.split()]:  # nav "Work" finds "Selected work"
            if len(word) > 2:
                ids.setdefault(anchor(word), sec_id)
    parts, alt = [], False
    for section, sec_id in zip(sections, section_ids, strict=True):
        kind = str(section["kind"])
        fields = section.get("fields") or {}
        body = RENDERERS[kind](fields, str(section.get("variant") or ""), button, ids)
        if kind in _BARE:
            parts.append(body)
            continue
        extra = " alt" if alt else ""
        alt = not alt
        variant = esc(section.get("variant") or "")
        parts.append(
            f'<section class="s {esc(kind)} v-{variant}{extra}" id="{sec_id}">{body}</section>'
        )
    title = esc(spec.get("name") or "My website")
    description = esc(spec.get("description") or "")
    css = _theme_css(theme, palettes or PALETTES, fonts or FONTS) + BASE_CSS
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<title>{title}</title><meta name="description" content="{description}">'
        f"<style>{css}</style></head><body>{''.join(parts)}</body></html>"
    )
