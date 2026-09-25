"""A designer's once-over for a web project: what would make it look finished."""

import re
from collections.abc import Mapping

_HEX = re.compile(r"#(?:[0-9a-fA-F]{3}){1,2}\b")
_RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")
_FONT_PX = re.compile(r"font-size\s*:\s*(\d+(?:\.\d+)?)px", re.I)
MIN_TEXT_PX = 14
MAX_COLORS = 14


def _rgb(hex_color: str) -> tuple[float, float, float]:
    value = hex_color.lstrip("#")
    if len(value) == 3:
        value = "".join(char * 2 for char in value)
    return (
        int(value[0:2], 16) / 255,
        int(value[2:4], 16) / 255,
        int(value[4:6], 16) / 255,
    )


def _luminance(hex_color: str) -> float:
    def channel(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in _rgb(hex_color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(first: str, second: str) -> float:
    """The WCAG contrast ratio between two hex colors (1 to 21)."""
    light, dark = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def _declared(block: str, name: str) -> str | None:
    match = re.search(rf"(?:^|;)\s*{name}\s*:\s*([^;]+)", block, re.I)
    return match.group(1).strip() if match else None


def _color_of(value: str | None, variables: Mapping[str, str]) -> str | None:
    if not value:
        return None
    var = re.search(r"var\(\s*(--[\w-]+)", value)
    if var:
        value = variables.get(var.group(1), "")
    found = _HEX.search(value)
    return found.group(0) if found else None


def polish_notes(files: Mapping[str, str]) -> list[str]:
    """Suggestions that make a working page look and feel finished."""
    css = "\n".join(text for path, text in files.items() if path.endswith(".css"))
    pages = {
        path: text for path, text in files.items() if path.endswith((".html", ".htm"))
    }
    inline = "\n".join(
        block
        for text in pages.values()
        for block in re.findall(r"<style[^>]*>(.*?)</style>", text, re.S | re.I)
    )
    styles = f"{css}\n{inline}"
    if not pages:
        return []
    notes: list[str] = []
    if not styles.strip():
        return [
            "The pages have no styles at all: add a stylesheet with a color scheme, spacing, and a readable font."
        ]
    variables = dict(re.findall(r"(--[\w-]+)\s*:\s*([^;}]+)", styles))
    rules = [(sel.strip(), body) for sel, body in _RULE.findall(styles)]
    body_rules = [
        body
        for sel, body in rules
        if re.search(r"(^|,)\s*(body|:root|html)\s*($|,)", sel)
    ]
    text_color = next(
        (c for b in body_rules if (c := _color_of(_declared(b, "color"), variables))),
        None,
    )
    background = next(
        (
            c
            for b in body_rules
            if (
                c := _color_of(
                    _declared(b, "background-color") or _declared(b, "background"),
                    variables,
                )
            )
        ),
        None,
    )
    if text_color and background and contrast(text_color, background) < 4.5:
        notes.append(
            f"Text {text_color} on {background} has a contrast of "
            f"{contrast(text_color, background):.1f}:1; make it at least 4.5:1 so it is easy to read."
        )
    if "@media" not in styles and not re.search(
        r"clamp\(|auto-fit|auto-fill|minmax\(", styles
    ):
        notes.append(
            "Nothing adapts to screen size: add @media rules or fluid sizes (clamp, grid auto-fit) so it works on phones."
        )
    if ":focus" not in styles:
        notes.append(
            "Add :focus-visible styles so keyboard users can see where they are."
        )
    clickable = re.search(r"(^|[\s,}])(a|button|\.button|\.btn)\b[^{]*\{", styles)
    if clickable and ":hover" not in styles:
        notes.append(
            "Buttons and links have no :hover state; give them one so they feel clickable."
        )
    tiny = sorted(
        {float(px) for px in _FONT_PX.findall(styles) if float(px) < MIN_TEXT_PX}
    )
    if tiny:
        notes.append(
            f"Some text is only {tiny[0]:g}px; keep body text at {MIN_TEXT_PX}px or more (16px is best)."
        )
    colors = {c.lower() for c in _HEX.findall(styles)}
    if len(colors) > MAX_COLORS and not variables:
        notes.append(
            f"{len(colors)} different colors are scattered through the CSS; put a small palette in :root variables and reuse it."
        )
    if not variables and len(colors) > 4:
        notes.append(
            "Define colors and spacing once as CSS variables in :root so the design stays consistent."
        )
    if "max-width" not in styles and "min(" not in styles:
        notes.append(
            "Content can stretch edge to edge on wide screens; give it a max-width (about 1100px) and center it."
        )
    if "line-height" not in styles:
        notes.append("Set a line-height around 1.5 for comfortable reading.")
    if "transition" not in styles and clickable:
        notes.append(
            "Add short transitions (150-250ms) to hovers and toggles so changes feel smooth."
        )
    for path, text in pages.items():
        if not re.search(r"<(header|nav|main|footer)\b", text, re.I):
            notes.append(
                f"{path}: use header, nav, main, and footer so the layout has clear structure."
            )
        if not re.search(r"<h1\b", text, re.I):
            notes.append(f"{path}: has no <h1> headline.")
        if re.search(r"<img\b(?![^>]*\b(?:width|height|loading)=)", text, re.I):
            notes.append(
                f'{path}: give images width and height (or loading="lazy") so the page does not jump while loading.'
            )
        if 'rel="icon"' not in text and "rel='icon'" not in text:
            notes.append(
                f'{path}: add a favicon (an emoji SVG works: <link rel="icon" href="data:image/svg+xml,...">).'
            )
    return notes[:20]
