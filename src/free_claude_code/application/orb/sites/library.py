"""The built-in UI library: palettes, font pairings, button styles, sections, starter sites.

Everything here is original to this project and works offline (system font stacks,
no web fonts, no CDN). Extra palettes, font pairings and layout presets can be added
to the owner's own library, but only with a free licence (see store.py).
"""

from typing import Any

# Each palette: page background, card surface, text, muted text, primary (buttons),
# text on primary, accent.
PALETTES: dict[str, dict[str, str]] = {
    "Espresso": {
        "bg": "#faf6f1",
        "surface": "#ffffff",
        "text": "#2b1d14",
        "muted": "#7a6455",
        "primary": "#6f4e37",
        "on_primary": "#ffffff",
        "accent": "#d4a373",
    },
    "Olive Grove": {
        "bg": "#f6f7f0",
        "surface": "#ffffff",
        "text": "#22281a",
        "muted": "#66705a",
        "primary": "#5a6b2f",
        "on_primary": "#ffffff",
        "accent": "#c9a227",
    },
    "Tomato Trattoria": {
        "bg": "#fffaf5",
        "surface": "#ffffff",
        "text": "#2a1512",
        "muted": "#7d5d55",
        "primary": "#c2412d",
        "on_primary": "#ffffff",
        "accent": "#2f6f4e",
    },
    "Night Bistro": {
        "bg": "#14110f",
        "surface": "#1f1a17",
        "text": "#f3ece4",
        "muted": "#b3a597",
        "primary": "#e0a458",
        "on_primary": "#1a1209",
        "accent": "#9c6644",
    },
    "Ocean Studio": {
        "bg": "#f3f8fb",
        "surface": "#ffffff",
        "text": "#0f2533",
        "muted": "#557083",
        "primary": "#1d6fa5",
        "on_primary": "#ffffff",
        "accent": "#f2a65a",
    },
    "Graphite": {
        "bg": "#f5f5f4",
        "surface": "#ffffff",
        "text": "#1c1917",
        "muted": "#6b6560",
        "primary": "#1c1917",
        "on_primary": "#ffffff",
        "accent": "#e4572e",
    },
    "Midnight Portfolio": {
        "bg": "#0e1116",
        "surface": "#171b22",
        "text": "#e8edf3",
        "muted": "#98a2b3",
        "primary": "#7c9cff",
        "on_primary": "#0b1020",
        "accent": "#ffcc66",
    },
    "Blush": {
        "bg": "#fdf6f6",
        "surface": "#ffffff",
        "text": "#2d1b22",
        "muted": "#7f6570",
        "primary": "#b4547a",
        "on_primary": "#ffffff",
        "accent": "#3d7a78",
    },
    "Forest Cabin": {
        "bg": "#f2f5f1",
        "surface": "#ffffff",
        "text": "#16241b",
        "muted": "#5d6f62",
        "primary": "#2d5a3d",
        "on_primary": "#ffffff",
        "accent": "#b5651d",
    },
    "Gold Standard": {
        "bg": "#0b0b0d",
        "surface": "#16161a",
        "text": "#f5f1e6",
        "muted": "#a8a196",
        "primary": "#ffc861",
        "on_primary": "#1a1300",
        "accent": "#40d6ff",
    },
}

# Offline font pairings (system fonts that ship with Windows/macOS, with safe fallbacks).
FONTS: dict[str, dict[str, Any]] = {
    "Modern Sans": {
        "heading": "'Segoe UI', system-ui, -apple-system, Roboto, sans-serif",
        "body": "'Segoe UI', system-ui, -apple-system, Roboto, sans-serif",
        "weight": 700,
        "tracking": "-0.01em",
    },
    "Classic Serif": {
        "heading": "Georgia, 'Times New Roman', serif",
        "body": "Georgia, 'Times New Roman', serif",
        "weight": 700,
        "tracking": "0",
    },
    "Editorial": {
        "heading": "'Palatino Linotype', 'Book Antiqua', Palatino, Georgia, serif",
        "body": "'Segoe UI', system-ui, sans-serif",
        "weight": 600,
        "tracking": "0",
    },
    "Elegant": {
        "heading": "Garamond, 'Baskerville Old Face', Baskerville, Georgia, serif",
        "body": "'Segoe UI', system-ui, sans-serif",
        "weight": 500,
        "tracking": "0.01em",
    },
    "Friendly Rounded": {
        "heading": "'Trebuchet MS', 'Segoe UI', sans-serif",
        "body": "Verdana, 'Segoe UI', sans-serif",
        "weight": 700,
        "tracking": "0",
    },
    "Bold Condensed": {
        "heading": "Impact, 'Arial Narrow Bold', 'Segoe UI', sans-serif",
        "body": "'Segoe UI', system-ui, sans-serif",
        "weight": 400,
        "tracking": "0.02em",
    },
    "Tech Mono": {
        "heading": "'Cascadia Code', Consolas, 'Courier New', monospace",
        "body": "'Segoe UI', system-ui, sans-serif",
        "weight": 600,
        "tracking": "-0.02em",
    },
}

BUTTONS: dict[str, str] = {
    "Solid": "Filled with the primary colour.",
    "Pill": "Filled and fully rounded.",
    "Outline": "Transparent with a primary border.",
    "Ghost": "Text only, a soft tint on hover.",
    "Gradient": "Primary-to-accent gradient.",
    "Lifted": "Solid with a strong shadow that lifts on hover.",
    "Underline": "Plain text with an underline that grows on hover.",
}

# Field types: text, long (paragraph), list (rows; columns given in "columns").
SECTION_KINDS: dict[str, dict[str, Any]] = {
    "nav": {
        "label": "Top bar",
        "variants": ["bar", "centered"],
        "fields": {"brand": "text", "links": {"columns": ["label"]}, "button": "text"},
    },
    "hero": {
        "label": "Hero (big intro)",
        "variants": ["centered", "split", "bold"],
        "fields": {
            "eyebrow": "text",
            "title": "text",
            "subtitle": "long",
            "button": "text",
            "button_link": "text",
            "secondary": "text",
            "image_url": "text",
        },
    },
    "about": {
        "label": "About",
        "variants": ["text", "two-column"],
        "fields": {"title": "text", "text": "long", "points": {"columns": ["point"]}},
    },
    "menu": {
        "label": "Menu with prices",
        "variants": ["columns", "cards"],
        "fields": {
            "title": "text",
            "items": {"columns": ["section", "name", "price", "description"]},
            "note": "text",
        },
    },
    "hours": {
        "label": "Opening hours",
        "variants": ["table"],
        "fields": {
            "title": "text",
            "rows": {"columns": ["day", "hours"]},
            "note": "text",
        },
    },
    "gallery": {
        "label": "Gallery",
        "variants": ["grid", "mosaic"],
        "fields": {"title": "text", "items": {"columns": ["caption", "image_url"]}},
    },
    "services": {
        "label": "Services / offers",
        "variants": ["cards", "list"],
        "fields": {
            "title": "text",
            "items": {"columns": ["name", "price", "description"]},
        },
    },
    "projects": {
        "label": "Projects / work",
        "variants": ["grid", "list"],
        "fields": {
            "title": "text",
            "items": {"columns": ["name", "tag", "description", "link"]},
        },
    },
    "skills": {
        "label": "Skills",
        "variants": ["tags", "bars"],
        "fields": {"title": "text", "items": {"columns": ["skill", "level"]}},
    },
    "testimonials": {
        "label": "Reviews",
        "variants": ["cards", "quote"],
        "fields": {"title": "text", "items": {"columns": ["quote", "name"]}},
    },
    "cta": {
        "label": "Call to action",
        "variants": ["band", "card"],
        "fields": {
            "title": "text",
            "text": "long",
            "button": "text",
            "button_link": "text",
        },
    },
    "contact": {
        "label": "Contact",
        "variants": ["split", "simple"],
        "fields": {
            "title": "text",
            "text": "long",
            "address": "text",
            "phone": "text",
            "email": "text",
            "form": "text",
        },
    },
    "footer": {
        "label": "Footer",
        "variants": ["simple", "columns"],
        "fields": {"text": "text", "links": {"columns": ["label", "url"]}},
    },
}

DEFAULT_THEME: dict[str, Any] = {
    "palette": "Espresso",
    "font": "Editorial",
    "button": "Pill",
    "radius": 14,
    "spacing": 1.0,
    "scale": 1.0,
    "shadow": 1,
    "width": 1120,
}


def _rows(*rows: tuple[str, ...]) -> list[list[str]]:
    return [list(r) for r in rows]


STARTERS: dict[str, dict[str, Any]] = {
    "restaurant": {
        "label": "Restaurant / café",
        "theme": {**DEFAULT_THEME, "palette": "Espresso", "font": "Editorial"},
        "sections": [
            {
                "kind": "nav",
                "variant": "bar",
                "fields": {
                    "brand": "The Corner Café",
                    "links": _rows(("Menu",), ("Hours",), ("Gallery",), ("Contact",)),
                    "button": "Book a table",
                },
            },
            {
                "kind": "hero",
                "variant": "split",
                "fields": {
                    "eyebrow": "Fresh every morning",
                    "title": "Good coffee, honest food, friendly faces.",
                    "subtitle": "A neighbourhood café serving seasonal breakfasts, slow-roasted coffee and cakes baked in-house.",
                    "button": "See the menu",
                    "button_link": "#menu",
                    "secondary": "Open today 8am - 5pm",
                    "image_url": "",
                },
            },
            {
                "kind": "about",
                "variant": "two-column",
                "fields": {
                    "title": "Our story",
                    "text": "We started with one espresso machine and a lot of stubbornness. Today we roast in small batches and cook with produce from farms within an hour of the café.",
                    "points": _rows(
                        ("Locally roasted coffee",),
                        ("Vegetarian and vegan options",),
                        ("Dog friendly",),
                    ),
                },
            },
            {
                "kind": "menu",
                "variant": "columns",
                "fields": {
                    "title": "Menu",
                    "items": _rows(
                        (
                            "Breakfast",
                            "Full breakfast",
                            "11.50",
                            "Eggs, smoked bacon, sausage, beans, toast",
                        ),
                        (
                            "Breakfast",
                            "Avocado toast",
                            "8.95",
                            "Sourdough, chilli, lime, poached egg",
                        ),
                        (
                            "Breakfast",
                            "Granola bowl",
                            "6.50",
                            "Greek yoghurt, berries, honey",
                        ),
                        ("Coffee", "Flat white", "3.40", "Double shot, silky milk"),
                        ("Coffee", "Cappuccino", "3.30", ""),
                        ("Coffee", "Iced latte", "3.80", "Oat milk available"),
                        ("Cakes", "Lemon drizzle", "3.20", "Baked this morning"),
                        ("Cakes", "Chocolate brownie", "3.00", "Gluten free"),
                    ),
                    "note": "Ask us about allergens.",
                },
            },
            {
                "kind": "hours",
                "variant": "table",
                "fields": {
                    "title": "Opening hours",
                    "rows": _rows(
                        ("Monday - Friday", "8:00 - 17:00"),
                        ("Saturday", "9:00 - 17:00"),
                        ("Sunday", "10:00 - 15:00"),
                    ),
                    "note": "Kitchen closes 30 minutes before we do.",
                },
            },
            {
                "kind": "gallery",
                "variant": "mosaic",
                "fields": {
                    "title": "From the counter",
                    "items": _rows(
                        ("Latte art", ""),
                        ("Sunday brunch", ""),
                        ("Fresh bakes", ""),
                        ("Our terrace", ""),
                    ),
                },
            },
            {
                "kind": "testimonials",
                "variant": "cards",
                "fields": {
                    "title": "What guests say",
                    "items": _rows(
                        (
                            "Best flat white in town, and the staff remember your order.",
                            "A regular",
                        ),
                        ("The brunch is worth the queue.", "Weekend visitor"),
                    ),
                },
            },
            {
                "kind": "contact",
                "variant": "split",
                "fields": {
                    "title": "Find us",
                    "text": "Walk-ins welcome. Book ahead for groups of six or more.",
                    "address": "12 Market Street",
                    "phone": "01234 567890",
                    "email": "hello@example.com",
                    "form": "yes",
                },
            },
            {
                "kind": "footer",
                "variant": "simple",
                "fields": {
                    "text": "The Corner Café",
                    "links": _rows(
                        ("Instagram", "https://instagram.com"),
                    ),
                },
            },
        ],
    },
    "portfolio": {
        "label": "Portfolio / personal brand",
        "theme": {
            **DEFAULT_THEME,
            "palette": "Midnight Portfolio",
            "font": "Modern Sans",
            "button": "Gradient",
            "radius": 18,
        },
        "sections": [
            {
                "kind": "nav",
                "variant": "bar",
                "fields": {
                    "brand": "Alex Morgan",
                    "links": _rows(("Work",), ("About",), ("Skills",), ("Contact",)),
                    "button": "Hire me",
                },
            },
            {
                "kind": "hero",
                "variant": "bold",
                "fields": {
                    "eyebrow": "Designer & developer",
                    "title": "I build clear, fast websites for small businesses.",
                    "subtitle": "Brand, design and code in one place, from first sketch to launch.",
                    "button": "See my work",
                    "button_link": "#projects",
                    "secondary": "Available for new projects",
                    "image_url": "",
                },
            },
            {
                "kind": "projects",
                "variant": "grid",
                "fields": {
                    "title": "Selected work",
                    "items": _rows(
                        (
                            "Harbour Bakery",
                            "Website",
                            "A booking-first site that doubled weekend orders.",
                            "",
                        ),
                        (
                            "Northside Physio",
                            "Branding",
                            "Logo, colours and a calm, accessible site.",
                            "",
                        ),
                        (
                            "Pixel Garden",
                            "Web app",
                            "A plant-care tracker with reminders.",
                            "",
                        ),
                    ),
                },
            },
            {
                "kind": "about",
                "variant": "text",
                "fields": {
                    "title": "About me",
                    "text": "I care about plain language, quick pages and designs people remember. I work with owners directly, so there is no agency between us.",
                    "points": _rows(),
                },
            },
            {
                "kind": "skills",
                "variant": "bars",
                "fields": {
                    "title": "Skills",
                    "items": _rows(
                        ("Web design", "90"),
                        ("HTML & CSS", "95"),
                        ("JavaScript", "80"),
                        ("Branding", "75"),
                    ),
                },
            },
            {
                "kind": "testimonials",
                "variant": "quote",
                "fields": {
                    "title": "Kind words",
                    "items": _rows(
                        (
                            "Alex understood our café in one meeting and the new site shows it.",
                            "Café owner",
                        ),
                    ),
                },
            },
            {
                "kind": "cta",
                "variant": "card",
                "fields": {
                    "title": "Have a project in mind?",
                    "text": "Tell me about it. I reply within a day.",
                    "button": "Get in touch",
                    "button_link": "#contact",
                },
            },
            {
                "kind": "contact",
                "variant": "simple",
                "fields": {
                    "title": "Contact",
                    "text": "",
                    "address": "",
                    "phone": "",
                    "email": "hello@example.com",
                    "form": "yes",
                },
            },
            {
                "kind": "footer",
                "variant": "simple",
                "fields": {
                    "text": "Alex Morgan",
                    "links": _rows(
                        ("GitHub", "https://github.com"),
                    ),
                },
            },
        ],
    },
    "blank": {
        "label": "Blank",
        "theme": dict(DEFAULT_THEME),
        "sections": [
            {
                "kind": "nav",
                "variant": "bar",
                "fields": {"brand": "My business", "links": _rows(), "button": ""},
            },
            {
                "kind": "hero",
                "variant": "centered",
                "fields": {
                    "eyebrow": "",
                    "title": "Welcome",
                    "subtitle": "Say what you do in one sentence.",
                    "button": "Contact us",
                    "button_link": "#contact",
                    "secondary": "",
                    "image_url": "",
                },
            },
            {
                "kind": "footer",
                "variant": "simple",
                "fields": {"text": "My business", "links": _rows()},
            },
        ],
    },
}


def empty_fields(kind: str) -> dict[str, Any]:
    spec = SECTION_KINDS[kind]["fields"]
    return {
        name: ([] if isinstance(kind_, dict) else "") for name, kind_ in spec.items()
    }


def library_summary(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    extra = extra or {}
    return {
        "palettes": {**PALETTES, **extra.get("palettes", {})},
        "fonts": {**FONTS, **extra.get("fonts", {})},
        "buttons": BUTTONS,
        "sections": SECTION_KINDS,
        "starters": {k: v["label"] for k, v in STARTERS.items()},
        "presets": extra.get("presets", {}),
        "credits": extra.get("credits", {}),
    }
