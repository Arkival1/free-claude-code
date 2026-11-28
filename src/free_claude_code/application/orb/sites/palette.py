"""Original colour palettes from colour theory, with readable contrast guaranteed."""

import colorsys
import re

HARMONIES = ("complementary", "analogous", "triadic", "split", "mono")
_HEX = re.compile(r"^#?([0-9a-fA-F]{6})$")
_HUE_NAMES = (
    (15, "Red"),
    (40, "Orange"),
    (65, "Gold"),
    (90, "Lime"),
    (150, "Green"),
    (190, "Teal"),
    (220, "Sky"),
    (255, "Blue"),
    (290, "Violet"),
    (330, "Magenta"),
    (360, "Red"),
)


def _rgb(hex_: str) -> tuple[float, float, float]:
    m = _HEX.match(hex_.strip())
    if not m:
        raise ValueError("Colours must look like #1d6fa5.")
    v = m.group(1)
    return (int(v[0:2], 16) / 255, int(v[2:4], 16) / 255, int(v[4:6], 16) / 255)


def _hex(rgb: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{round(max(0.0, min(1.0, c)) * 255):02x}" for c in rgb)


def _hls(h: float, light: float, sat: float) -> str:
    return _hex(
        colorsys.hls_to_rgb(
            (h % 360) / 360, max(0.0, min(1.0, light)), max(0.0, min(1.0, sat))
        )
    )


def luminance(hex_: str) -> float:
    def channel(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in _rgb(hex_))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _readable(
    h: float, sat: float, start: float, bg: str, minimum: float, step: float
) -> str:
    light = start
    for _ in range(40):
        colour = _hls(h, light, sat)
        if contrast(colour, bg) >= minimum:
            return colour
        light += step
    return "#000000" if step < 0 else "#ffffff"


def original_palette(
    base: str, harmony: str = "complementary", mode: str = "light"
) -> dict[str, str]:
    """A new palette built around ``base``; text always meets WCAG contrast (7:1 body, 4.5:1 buttons)."""
    if harmony not in HARMONIES:
        raise ValueError(f"harmony must be one of {', '.join(HARMONIES)}")
    r, g, b = _rgb(base)
    h, light, sat = colorsys.rgb_to_hls(r, g, b)
    h *= 360
    accent_h = {
        "complementary": h + 180,
        "analogous": h + 35,
        "triadic": h + 120,
        "split": h + 150,
        "mono": h,
    }[harmony]
    dark = mode == "dark"
    bg = _hls(h, 0.07 if dark else 0.975, 0.18 if dark else 0.35)
    surface = _hls(h, 0.11 if dark else 1.0, 0.14 if dark else 0.0)
    text = _readable(h, 0.2, 0.93 if dark else 0.12, bg, 7.0, 0.02 if dark else -0.02)
    muted = _readable(h, 0.12, 0.70 if dark else 0.42, bg, 4.5, 0.03 if dark else -0.03)
    primary = _readable(
        h,
        max(sat, 0.45),
        0.62 if dark else max(0.30, min(light, 0.48)),
        bg,
        3.0,
        0.03 if dark else -0.03,
    )
    on_primary = (
        "#ffffff"
        if contrast("#ffffff", primary) >= contrast("#111111", primary)
        else "#111111"
    )
    accent = _hls(
        accent_h, 0.62 if dark else 0.5, max(sat, 0.5) if harmony != "mono" else 0.3
    )
    return {
        "bg": bg,
        "surface": surface,
        "text": text,
        "muted": muted,
        "primary": primary,
        "on_primary": on_primary,
        "accent": accent,
    }


def palette_name(base: str, harmony: str) -> str:
    h = colorsys.rgb_to_hls(*_rgb(base))[0] * 360
    hue = next(name for limit, name in _HUE_NAMES if h <= limit)
    return f"Original {hue} {harmony.title()}"
