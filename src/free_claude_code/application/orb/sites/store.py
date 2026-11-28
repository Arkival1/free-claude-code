"""Sites and the owner's own design library, stored as JSON in FCC's config folder."""

import contextlib
import copy
import json
import re
import threading
from pathlib import Path
from typing import Any

from .library import (
    DEFAULT_THEME,
    FONTS,
    PALETTES,
    SECTION_KINDS,
    STARTERS,
    empty_fields,
    library_summary,
)
from .palette import HARMONIES, original_palette, palette_name
from .render import render_site

# Licences that let anyone reuse a design without asking: no copyrighted designs.
FREE_LICENCES = {
    "cc0": "CC0",
    "public domain": "Public domain",
    "unlicense": "Unlicense",
    "mit": "MIT",
    "ofl": "OFL",
    "sil ofl": "OFL",
    "apache-2.0": "Apache-2.0",
    "apache 2.0": "Apache-2.0",
}
MAX_SECTIONS, MAX_ROWS, MAX_TEXT = 40, 80, 4000
_SLUG = re.compile(r"[^a-z0-9]+")
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_FONT_STACK = re.compile(r"^[A-Za-z0-9 ,'\-]{3,200}$")


class SiteError(ValueError):
    """A site or library request that cannot be done; the message says why."""


def slugify(name: str) -> str:
    slug = _SLUG.sub("-", name.lower()).strip("-")[:48]
    if not slug:
        raise SiteError("Give the site a name with letters or numbers.")
    return slug


def _text(value: Any) -> str:
    return str(value if value is not None else "")[:MAX_TEXT]


class SiteStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._lock = threading.Lock()

    # ---------- library ----------
    def _library_path(self) -> Path:
        return self.root / "library.json"

    def user_library(self) -> dict[str, Any]:
        try:
            data = json.loads(self._library_path().read_text(encoding="utf-8"))
        except OSError, ValueError:
            data = {}
        return {k: data.get(k, {}) for k in ("palettes", "fonts", "presets", "credits")}

    def library(self) -> dict[str, Any]:
        return library_summary(self.user_library())

    def add_design(
        self, kind: str, name: str, data: Any, source_url: str, licence: str
    ) -> dict[str, Any]:
        """Add a palette, font pairing or layout preset found online, only with a free licence."""
        kind = (kind or "").strip().lower().rstrip("s")
        name = re.sub(r"[^A-Za-z0-9 &'\-]", "", str(name or "")).strip()[:40]
        free = FREE_LICENCES.get(str(licence or "").strip().lower())
        if not free:
            raise SiteError(
                "Only designs with a free licence can be added (CC0, public domain, Unlicense, MIT, OFL, "
                "Apache-2.0). Copyrighted designs are not allowed; make an original one instead."
            )
        if not re.match(r"^https?://\S+$", str(source_url or "")):
            raise SiteError(
                "Give the source_url where the design and its licence were found."
            )
        if not name:
            raise SiteError("Give the design a short name.")
        if kind == "palette":
            if not isinstance(data, dict) or not all(
                _HEX.match(str(data.get(k, ""))) for k in ("bg", "text", "primary")
            ):
                raise SiteError(
                    'A palette needs hex colours, at least {"bg": "#...", "text": "#...", "primary": "#..."}.'
                )
            item = {
                k: str(data.get(k) or data.get("primary"))
                for k in (
                    "bg",
                    "surface",
                    "text",
                    "muted",
                    "primary",
                    "on_primary",
                    "accent",
                )
            }
            item = {k: v if _HEX.match(v) else "#888888" for k, v in item.items()}
            group = "palettes"
        elif kind == "font":
            if not isinstance(data, dict) or not all(
                _FONT_STACK.match(str(data.get(k, ""))) for k in ("heading", "body")
            ):
                raise SiteError(
                    'A font pairing needs {"heading": "font stack", "body": "font stack"} using installed fonts.'
                )
            item = {
                "heading": str(data["heading"]),
                "body": str(data["body"]),
                "weight": int(data.get("weight", 700))
                if str(data.get("weight", "700")).isdigit()
                else 700,
                "tracking": "0",
            }
            group = "fonts"
        elif kind == "preset":
            if not isinstance(data, dict):
                raise SiteError(
                    'A preset needs {"sections": [...kinds...], "theme": {...}}.'
                )
            order = [k for k in data.get("sections", []) if k in SECTION_KINDS][
                :MAX_SECTIONS
            ]
            if not order:
                raise SiteError(
                    f"A preset lists section kinds from: {', '.join(SECTION_KINDS)}."
                )
            item = {"sections": order, "theme": self._theme(data.get("theme") or {})}
            group = "presets"
        else:
            raise SiteError("kind must be palette, font or preset.")
        with self._lock:
            lib = self.user_library()
            lib[group][name] = item
            lib["credits"][f"{group}:{name}"] = {"source": source_url, "licence": free}
            self.root.mkdir(parents=True, exist_ok=True)
            self._library_path().write_text(json.dumps(lib, indent=1), encoding="utf-8")
        return {"added": name, "kind": kind, "licence": free}

    # ---------- sites ----------
    def _path(self, slug: str) -> Path:
        return self.root / f"{slugify(slug)}.json"

    def sites(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for path in sorted(self.root.glob("*.json")) if self.root.is_dir() else []:
            if path.name == "library.json":
                continue
            try:
                spec = json.loads(path.read_text(encoding="utf-8"))
            except OSError, ValueError:
                continue
            out.append(
                {
                    "slug": path.stem,
                    "name": spec.get("name", path.stem),
                    "kind": spec.get("kind", ""),
                    "sections": len(spec.get("sections", [])),
                    "updated": path.stat().st_mtime,
                }
            )
        return sorted(out, key=lambda s: -float(s["updated"]))

    def get(self, slug: str) -> dict[str, Any]:
        try:
            return json.loads(self._path(slug).read_text(encoding="utf-8"))
        except OSError as exc:
            raise SiteError(
                f"No site called {slug!r}. Use site_list to see your sites."
            ) from exc

    def create(
        self,
        name: str,
        kind: str = "restaurant",
        description: str = "",
        preset: str = "",
    ) -> dict[str, Any]:
        slug = slugify(name)
        if slug in {"library", "render", "palette", "export"}:
            raise SiteError("That name is reserved. Pick another name.")
        if self._path(slug).exists():
            raise SiteError(
                f"A site called {slug!r} already exists. Pick another name or edit that one."
            )
        starter = STARTERS.get(kind) or STARTERS["blank"]
        spec = {
            "name": str(name)[:80],
            "slug": slug,
            "kind": kind if kind in STARTERS else "blank",
            "description": _text(description)[:300],
            "theme": copy.deepcopy(starter["theme"]),
            "sections": copy.deepcopy(starter["sections"]),
        }
        user_preset = self.user_library()["presets"].get(preset)
        if user_preset:
            spec["theme"] = {**spec["theme"], **user_preset["theme"]}
            have = {s["kind"]: s for s in spec["sections"]}
            spec["sections"] = [
                have.get(k)
                or {
                    "kind": k,
                    "variant": SECTION_KINDS[k]["variants"][0],
                    "fields": empty_fields(k),
                }
                for k in user_preset["sections"]
            ]
        for section in spec["sections"]:
            if section["kind"] == "nav":
                section["fields"]["brand"] = spec["name"]
            if section["kind"] == "footer":
                section["fields"]["text"] = spec["name"]
            if section["kind"] == "hero" and spec["description"]:
                section["fields"]["subtitle"] = spec["description"]
        return self.save(slug, spec)

    def save(self, slug: str, spec: Any) -> dict[str, Any]:
        clean = self.clean(spec)
        clean["slug"] = slugify(slug)
        with self._lock:
            self.root.mkdir(parents=True, exist_ok=True)
            tmp = self._path(slug).with_suffix(".tmp")
            tmp.write_text(
                json.dumps(clean, indent=1, ensure_ascii=False), encoding="utf-8"
            )
            tmp.replace(self._path(slug))
        return clean

    def render(self, spec: dict[str, Any]) -> str:
        lib = self.library()
        return render_site(self.clean(spec), lib["palettes"], lib["fonts"])

    def export(self, slug: str) -> dict[str, Any]:
        spec = self.get(slug)
        html_text = self.render(spec)
        folder = self.root / "export" / slugify(slug)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "index.html").write_text(html_text, encoding="utf-8")
        return {
            "slug": slugify(slug),
            "folder": str(folder),
            "file": str(folder / "index.html"),
            "html": html_text,
        }

    def make_palette(
        self, base: str, harmony: str = "complementary", mode: str = "light"
    ) -> dict[str, Any]:
        if harmony not in HARMONIES:
            raise SiteError(f"harmony must be one of {', '.join(HARMONIES)}")
        try:
            colours = original_palette(
                base, harmony, "dark" if mode == "dark" else "light"
            )
            name = palette_name(base, harmony) + (" Dark" if mode == "dark" else "")
        except ValueError as exc:
            raise SiteError(str(exc)) from exc
        return {"name": name, "colours": colours}

    # ---------- small edits (used by JARVIS's tools) ----------
    def _find(self, spec: dict[str, Any], which: Any) -> int:
        sections = spec["sections"]
        if isinstance(which, int) or str(which).isdigit():
            index = int(which)
            if 0 <= index < len(sections):
                return index
        else:
            for index, section in enumerate(sections):
                if section["kind"] == str(which).strip().lower():
                    return index
        kinds = ", ".join(f"{i}:{s['kind']}" for i, s in enumerate(sections))
        raise SiteError(f"No section {which!r}. This site has: {kinds}")

    def edit_section(
        self, slug: str, which: Any, fields: Any = None, variant: str = ""
    ) -> dict[str, Any]:
        spec = self.get(slug)
        index = self._find(spec, which)
        section = spec["sections"][index]
        if isinstance(fields, dict):
            section["fields"].update(fields)
        if variant:
            section["variant"] = variant
        return self.save(slug, spec)["sections"][index]

    def add_section(
        self, slug: str, kind: str, variant: str = "", position: int = -1
    ) -> dict[str, Any]:
        if kind not in SECTION_KINDS:
            raise SiteError(
                f"Unknown section kind. Choose from: {', '.join(SECTION_KINDS)}"
            )
        spec = self.get(slug)
        section = {
            "kind": kind,
            "variant": variant or SECTION_KINDS[kind]["variants"][0],
            "fields": empty_fields(kind),
        }
        footer = next(
            (i for i, s in enumerate(spec["sections"]) if s["kind"] == "footer"),
            len(spec["sections"]),
        )
        at = (
            footer
            if position is None or position < 0
            else min(position, len(spec["sections"]))
        )
        spec["sections"].insert(at, section)
        self.save(slug, spec)
        return {
            "index": at,
            "kind": kind,
            "fields": list(SECTION_KINDS[kind]["fields"]),
        }

    def remove_section(self, slug: str, which: Any) -> dict[str, Any]:
        spec = self.get(slug)
        index = self._find(spec, which)
        removed = spec["sections"].pop(index)
        self.save(slug, spec)
        return {
            "removed": removed["kind"],
            "left": [s["kind"] for s in spec["sections"]],
        }

    def set_theme(self, slug: str, **changes: Any) -> dict[str, Any]:
        spec = self.get(slug)
        spec["theme"].update(
            {k: v for k, v in changes.items() if v not in (None, "", -1)}
        )
        return self.save(slug, spec)["theme"]

    def apply_palette(
        self, slug: str, base: str, harmony: str = "complementary", mode: str = "light"
    ) -> dict[str, Any]:
        made = self.make_palette(base, harmony, mode)
        self.set_theme(slug, palette=made["colours"])
        return made

    # ---------- validation ----------
    def _theme(self, theme: Any) -> dict[str, Any]:
        theme = theme if isinstance(theme, dict) else {}
        lib = self.library()
        out = dict(DEFAULT_THEME)
        pal = theme.get("palette", out["palette"])
        if isinstance(pal, dict):
            out["palette"] = {
                k: str(pal.get(k)) if _HEX.match(str(pal.get(k, ""))) else "#888888"
                for k in (
                    "bg",
                    "surface",
                    "text",
                    "muted",
                    "primary",
                    "on_primary",
                    "accent",
                )
            }
        elif str(pal) in lib["palettes"]:
            out["palette"] = str(pal)
        if str(theme.get("font", "")) in lib["fonts"]:
            out["font"] = str(theme["font"])
        if str(theme.get("button", "")) in lib["buttons"]:
            out["button"] = str(theme["button"])
        for key, low, high, kind in (
            ("radius", 0, 40, int),
            ("spacing", 0.6, 1.6, float),
            ("scale", 0.8, 1.3, float),
            ("shadow", 0, 3, int),
            ("width", 760, 1440, int),
        ):
            with contextlib.suppress(TypeError, ValueError):
                out[key] = kind(max(low, min(high, float(theme.get(key, out[key])))))
        return out

    def clean(self, spec: Any) -> dict[str, Any]:
        if not isinstance(spec, dict):
            raise SiteError("A site must be a JSON object.")
        sections = []
        for section in (spec.get("sections") or [])[:MAX_SECTIONS]:
            if (
                not isinstance(section, dict)
                or section.get("kind") not in SECTION_KINDS
            ):
                continue
            kind = section["kind"]
            info = SECTION_KINDS[kind]
            variant = (
                section.get("variant")
                if section.get("variant") in info["variants"]
                else info["variants"][0]
            )
            given = (
                section.get("fields") if isinstance(section.get("fields"), dict) else {}
            )
            fields: dict[str, Any] = {}
            for name, ftype in info["fields"].items():
                value = given.get(name)
                if isinstance(ftype, dict):
                    width = len(ftype["columns"])
                    rows = value if isinstance(value, list) else []
                    fields[name] = [
                        ([_text(c)[:600] for c in r] + [""] * width)[:width]
                        if isinstance(r, list)
                        else ([_text(r)[:600]] + [""] * width)[:width]
                        for r in rows[:MAX_ROWS]
                    ]
                else:
                    fields[name] = _text(value)
            sections.append({"kind": kind, "variant": variant, "fields": fields})
        return {
            "name": _text(spec.get("name") or "My website")[:80],
            "slug": str(spec.get("slug", "")),
            "kind": str(spec.get("kind", "blank"))[:20],
            "description": _text(spec.get("description"))[:300],
            "theme": self._theme(spec.get("theme")),
            "sections": sections,
        }


__all__ = ["FONTS", "FREE_LICENCES", "PALETTES", "SiteError", "SiteStore", "slugify"]
