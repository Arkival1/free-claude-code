"""Designs: a piece of technology drawn in its real materials, and checked
against real physics.

A design is a list of components. Each is made of a material from the
Lab's shelf (steel, iron, copper, aluminium, a circuit board, glass, wood,
plastics...), has a shape and a size, and may be an electronics part from
the parts bin (a battery, a motor, an LED, a microcontroller). Saved parts
can be dropped into any design and are expanded into their components.

The check works out, with handbook numbers:
- the weight of every component (its volume times its material's density,
  or the part's own weight) and of the whole design, and what it is made of;
- for each member that carries a load, the stress in it against its
  material's strength (pulling or pressing straight; bending and buckling
  aren't modelled, so the margin asked for is generous);
- the electronics, on the circuit bench: the voltage, the current each part
  draws, the runtime, and anything that would burn out or not switch on;
- the heat the electronics give off and how hot the casing would get, and
  whether its material would soften;
- a metal casing around live electronics, rust in the wet, two metals that
  corrode each other when wet, and whether the whole thing floats.
Each component also says how it works. These are estimates for a sketch,
not an engineer's sign-off.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from . import materials, tech
from .data import LabData
from .sim import LabError

SHAPES = ("box", "plate", "board", "rod", "cylinder", "tube", "sphere", "wire")
ROLES = ("structure", "casing", "electronics", "moving", "wiring", "fastener", "other")
MAX_COMPONENTS = 80
GRAVITY = 9.81
SHOCK = 2.0
"""Loads are doubled for bumps and drops."""
SAFE = 3.0
"""The margin a load-bearing member should have (straight loads only)."""
CONVECTION = 10.0
"""W per m² per °C: still air carrying heat off a surface."""
AMBIENT_C = 25.0
WALL_MM = 2.5
"""A casing is hollow: its walls are this thick unless the design says."""
CONDUCTIVE = 1e-4
"""Below this resistivity (Ω·m) a material conducts electricity."""
GALVANIC_NOBLE = {"copper", "brass", "bronze", "stainless-steel", "gold", "silver"}
GALVANIC_BASE = {"aluminium", "duralumin", "zinc", "magnesium", "steel", "iron"}

_FINISH_BY_ID = {
    "fr4": "board",
    "carbon-fibre": "weave",
    "kevlar": "weave",
    "rubber": "rubber",
    "silicone": "rubber",
    "wood-oak": "wood",
    "wood-pine": "wood",
    "bamboo": "wood",
    "cotton": "fibre",
    "spider-silk": "fibre",
    "silicon": "wafer",
    "gallium-arsenide": "wafer",
    "diamond": "gem",
    "concrete": "stone",
}
_FINISH_BY_CATEGORY = {
    "metal": "metal",
    "alloy": "metal",
    "polymer": "plastic",
    "ceramic": "ceramic",
    "glass": "glass",
    "composite": "fibre",
    "natural": "fibre",
    "semiconductor": "wafer",
}
_PART_MATERIAL = {
    "power": "steel",
    "charger": "fr4",
    "regulator": "fr4",
    "light": "epoxy",
    "motion": "steel",
    "sound": "abs",
    "brain": "fr4",
    "sensor": "fr4",
    "display": "glass",
    "control": "abs",
    "passive": "copper",
    "structure": "abs",
}
"""What an electronics part is mostly made of, when the design doesn't say."""


def finish(material: materials.Material) -> str:
    """How the material looks: metal, plastic, board, wood, glass..."""
    return _FINISH_BY_ID.get(
        material.id, _FINISH_BY_CATEGORY.get(material.category, "plastic")
    )


@dataclass(frozen=True, slots=True)
class Component:
    name: str
    material: materials.Material
    shape: str
    size_mm: tuple[float, float, float]
    count: int
    role: str
    part: tech.Part | None
    how: str
    carries_kg: float
    wall_mm: float = 0.0
    """A casing's wall thickness (it is hollow); 0 for solid parts."""
    at_mm: tuple[float, float, float] | None = None
    """Where it sits in the 3D view (x across, y up, z towards you, from the
    middle of the floor); None lets the view lay it out."""
    turn_deg: float = 0.0
    """How far it is turned about the upright axis in the 3D view."""

    def volume_cm3(self) -> float:
        w, h, d = self.size_mm
        if self.wall_mm and self.shape in {"box", "cylinder", "sphere"}:
            return self._shell_mm3(w, h, d) / 1000
        if self.shape in {"rod", "cylinder", "wire"}:
            mm3 = math.pi * (w / 2) ** 2 * h
        elif self.shape == "tube":
            inner = w * 0.8
            mm3 = math.pi * ((w / 2) ** 2 - (inner / 2) ** 2) * h
        elif self.shape == "sphere":
            mm3 = 4 / 3 * math.pi * (w / 2) ** 3
        else:
            mm3 = w * h * d
        return mm3 / 1000

    def _shell_mm3(self, w: float, h: float, d: float) -> float:
        """The material in a hollow casing: the outside less the inside."""
        wall = min(self.wall_mm, min(value for value in (w, h, d) if value > 0) / 4)
        if self.shape == "sphere":
            return 4 / 3 * math.pi * ((w / 2) ** 3 - (w / 2 - wall) ** 3)
        if self.shape == "cylinder":
            return math.pi * h * ((w / 2) ** 2 - (w / 2 - wall) ** 2) + 2 * (
                math.pi * (w / 2) ** 2 * wall
            )
        inner = max(0.0, w - 2 * wall) * max(0.0, h - 2 * wall) * max(0.0, d - 2 * wall)
        return w * h * d - inner

    def section_mm2(self) -> float:
        """The cross-section a straight load goes through: a rod's round
        end, a plate's or board's edge (width x thickness), a block's base."""
        w, h, d = self.size_mm
        if self.shape in {"plate", "board"}:
            return w * h
        if self.shape in {"rod", "cylinder", "wire"}:
            return math.pi * (w / 2) ** 2
        if self.shape == "tube":
            return math.pi * ((w / 2) ** 2 - (w * 0.4) ** 2)
        if self.shape == "sphere":
            return math.pi * (w / 2) ** 2
        return w * d

    def surface_m2(self) -> float:
        w, h, d = self.size_mm
        if self.shape in {"rod", "cylinder", "tube", "wire"}:
            mm2 = math.pi * w * h + 2 * math.pi * (w / 2) ** 2
        elif self.shape == "sphere":
            mm2 = math.pi * w**2
        else:
            mm2 = 2 * (w * h + w * d + h * d)
        return mm2 / 1_000_000

    def mass_g(self) -> float:
        if self.part is not None and self.part.grams:
            return self.part.grams * self.count
        return self.volume_cm3() * self.material.density * self.count


def _size(value: object, shape: str) -> tuple[float, float, float]:
    numbers: list[float] = []
    if isinstance(value, Mapping):
        for key in ("w", "h", "d"):
            item = value.get(key)
            numbers.append(float(item) if isinstance(item, int | float) else 0.0)
    elif isinstance(value, Sequence) and not isinstance(value, str):
        numbers = [float(item) for item in value if isinstance(item, int | float)]
    defaults = {"wire": (1.0, 100.0, 0.0), "board": (50.0, 1.6, 70.0)}.get(
        shape, (40.0, 40.0, 40.0)
    )
    filled = [
        numbers[index]
        if index < len(numbers) and numbers[index] > 0
        else defaults[index]
        for index in range(3)
    ]
    return (
        min(filled[0], 10_000.0),
        min(filled[1], 10_000.0),
        min(filled[2], 10_000.0),
    )


MAX_REACH_MM = 10_000.0
"""How far from the middle a component may be placed."""


def _number(value: object) -> float | None:
    """A finite number, or None (bools, text and huge values aren't)."""
    if not isinstance(value, int | float) or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if math.isfinite(number) else None


def _place(value: object) -> tuple[float, float, float] | None:
    """A position [x, y, z] or {x, y, z} in mm, or None when not given."""
    if isinstance(value, Mapping):
        value = [value.get(key) for key in ("x", "y", "z")]
    if not isinstance(value, Sequence) or isinstance(value, str) or len(value) < 3:
        return None
    numbers = [_number(item) for item in list(value)[:3]]
    if len(numbers) < 3 or any(n is None for n in numbers):
        return None
    x, y, z = (max(-MAX_REACH_MM, min(MAX_REACH_MM, n or 0.0)) for n in numbers)
    return (round(x, 1), round(y, 1), round(z, 1))


def _turn(value: object) -> float:
    number = _number(value)
    return 0.0 if number is None else round(number, 1) % 360


def read_component(entry: Mapping[str, object]) -> Component:
    """A component from what was asked; an unknown material or part is
    refused (never guessed)."""
    part = None
    part_name = str(entry.get("part") or "").strip()
    if part_name:
        part = tech.find(part_name)
        if part is None:
            raise LabError(f"No electronics part called {part_name!r}.")
    material_name = str(entry.get("material") or "").strip()
    if not material_name and part is not None:
        material_name = _PART_MATERIAL.get(part.kind, "abs")
    material = materials.find(material_name or "abs")
    if material is None:
        raise LabError(
            f"No material called {material_name!r}: pick one from the Materials "
            "shelf (steel, iron, copper, aluminium, fr4, abs, glass, wood-oak...)."
        )
    shape = str(entry.get("shape") or ("board" if material.id == "fr4" else "box"))
    if shape not in SHAPES:
        shape = "box"
    role = str(entry.get("role") or ("electronics" if part else "structure"))
    if role not in ROLES:
        role = "other"
    raw_count = entry.get("count")
    count = (
        int(raw_count) if isinstance(raw_count, int | float) and raw_count >= 1 else 1
    )
    load = entry.get("carries_kg")
    wall = entry.get("wall_mm")
    name = str(entry.get("name") or (part.name if part else material.name)).strip()
    return Component(
        name=name[:80] or material.name,
        material=material,
        shape=shape,
        size_mm=_size(entry.get("size_mm"), shape),
        count=min(count, 100),
        role=role,
        part=part,
        how=str(entry.get("how") or "").strip()[:400],
        carries_kg=float(load) if isinstance(load, int | float) and load > 0 else 0.0,
        wall_mm=(float(wall) if isinstance(wall, int | float) and wall > 0 else WALL_MM)
        if role == "casing" and part is None
        else 0.0,
        at_mm=_place(entry.get("at_mm")),
        turn_deg=_turn(entry.get("turn_deg")),
    )


def _how(component: Component) -> str:
    if component.how:
        return component.how
    if component.part is not None and component.part.note:
        return component.part.note
    role = {
        "structure": "holds the design together and takes the loads",
        "casing": "protects what is inside and carries its heat away",
        "electronics": "does the electrical work",
        "moving": "moves",
        "wiring": "carries the current between parts",
        "fastener": "holds parts together",
    }.get(component.role, "is part of the design")
    uses = (
        f" {component.material.name}: {component.material.uses}"
        if component.material.uses
        else ""
    )
    return f"It {role}.{uses}".strip()


def check(
    entries: Sequence[Mapping[str, object]],
    *,
    name: str = "My design",
    wet: bool = False,
    series: bool = True,
) -> LabData:
    if not entries:
        raise LabError("Add some components to the design first.")
    if len(entries) > MAX_COMPONENTS:
        raise LabError(f"A design can have up to {MAX_COMPONENTS} components.")
    components = [read_component(entry) for entry in entries]
    checks: list[LabData] = []
    warnings: list[str] = []
    notes: list[str] = []

    # Electronics on the circuit bench.
    bill: dict[str, int] = {}
    for component in components:
        if component.part is not None:
            bill[component.part.id] = bill.get(component.part.id, 0) + component.count
    electronics: LabData | None = None
    states: dict[str, str] = {}
    if bill:
        electronics = tech.simulate_build(
            [{"id": part, "count": count} for part, count in bill.items()],
            series=series,
        )
        for row in electronics.get("parts") or []:
            if isinstance(row, dict):
                states[str(row.get("id"))] = str(row.get("state") or "")
        powered = bool(electronics.get("works"))
        checks.append(
            {
                "name": "Electronics",
                "ok": powered,
                "detail": f"{electronics.get('volts')} V, {electronics.get('total_ma')} mA, "
                f"runs {electronics.get('runtime_text')}"
                if powered
                else "; ".join(str(w) for w in electronics.get("warnings") or [])[:300]
                or "not working",
            }
        )

    # Weight and what it is made of.
    total = sum(component.mass_g() for component in components)
    by_material: dict[str, float] = {}
    for component in components:
        by_material[component.material.id] = (
            by_material.get(component.material.id, 0.0) + component.mass_g()
        )

    # Loads.
    rows: list[LabData] = []
    weakest: float | None = None
    for component in components:
        stress = factor = None
        verdict = ""
        if component.carries_kg:
            force = component.carries_kg * GRAVITY * SHOCK / component.count
            area = component.section_mm2()
            stress = force / area if area > 0 else math.inf
            factor = component.material.strength / stress if stress else math.inf
            weakest = factor if weakest is None else min(weakest, factor)
            verdict = (
                "breaks"
                if factor < 1
                else "risky"
                if factor < 1.5
                else "OK"
                if factor < SAFE
                else "strong"
            )
            if factor < 1.5:
                warnings.append(
                    f"{component.name} ({component.material.name}) carries "
                    f"{component.carries_kg:g} kg with a margin of only {factor:.1f}x: "
                    "make it thicker or use a stronger material."
                )
        state = states.get(component.part.id, "") if component.part else ""
        rows.append(
            {
                "name": component.name,
                "count": component.count,
                "role": component.role,
                "shape": component.shape,
                "size_mm": list(component.size_mm),
                "part": component.part.id if component.part else "",
                "part_kind": component.part.kind if component.part else "",
                "icon": component.part.icon if component.part else "",
                "at_mm": list(component.at_mm) if component.at_mm else None,
                "turn_deg": component.turn_deg,
                "material": {
                    "id": component.material.id,
                    "name": component.material.name,
                    "category": component.material.category,
                    "colour": component.material.colour,
                    "finish": finish(component.material),
                    "strength_mpa": component.material.strength,
                    "density": component.material.density,
                    "melts_c": component.material.melts,
                    "rusts": component.material.rusts,
                },
                "mass_g": round(component.mass_g(), 1),
                "carries_kg": component.carries_kg,
                "stress_mpa": round(stress, 2)
                if stress is not None and math.isfinite(stress)
                else None,
                "safety_factor": round(min(factor, 999.0), 2)
                if factor is not None and math.isfinite(factor)
                else None,
                "verdict": verdict,
                "state": state,
                "rusting": wet and component.material.rusts in {"yes", "slowly"},
                "how": _how(component),
            }
        )
    if weakest is not None:
        checks.append(
            {
                "name": "Strength",
                "ok": weakest >= 1.5,
                "detail": "weakest load-bearing member has a "
                + (f"{weakest:.1f}x" if weakest < 100 else "over 100x")
                + f" margin (aim for {SAFE:g}x; straight loads only)",
            }
        )

    # Heat from the electronics, through the casing.
    watts = float(electronics.get("watts") or 0.0) if electronics else 0.0
    casing = [c for c in components if c.role == "casing"]
    if watts > 0 and casing:
        area = sum(c.surface_m2() * c.count for c in casing)
        rise = watts / (CONVECTION * area) if area > 0 else 0.0
        hottest = AMBIENT_C + rise
        softest = min(casing, key=lambda c: c.material.melts)
        cool_enough = hottest < softest.material.melts - 20
        checks.append(
            {
                "name": "Heat",
                "ok": cool_enough,
                "detail": f"{watts:.2f} W of heat; the casing reaches about "
                f"{hottest:.0f} °C ({softest.material.name} softens near "
                f"{softest.material.melts:g} °C)",
            }
        )
        if not cool_enough:
            warnings.append(
                f"The {softest.material.name} casing would get too hot: add vents, "
                "a fan, or a metal casing that spreads the heat."
            )
        if rise > 15:
            notes.append(
                f"The casing runs about {rise:.0f} °C above the room: warm to touch."
            )

    # A metal casing around live electronics.
    if bill and any(c.material.resistivity < CONDUCTIVE for c in casing):
        notes.append(
            "The casing conducts electricity: mount the boards on insulating "
            "standoffs and insulate the wires where they pass through it."
        )

    # Water.
    if wet:
        rusty = sorted(
            {c.material.name for c in components if c.material.rusts == "yes"}
        )
        if rusty:
            warnings.append(
                f"{', '.join(rusty)} rusts in the wet: paint or coat it, or use "
                "stainless steel or aluminium."
            )
        metals = {c.material.id for c in components}
        if metals & GALVANIC_NOBLE and metals & GALVANIC_BASE:
            warnings.append(
                "Two different metals touching in the wet corrode each other "
                f"({', '.join(sorted(metals & GALVANIC_BASE))} against "
                f"{', '.join(sorted(metals & GALVANIC_NOBLE))}): separate them with "
                "plastic or rubber washers."
            )
        if bill:
            notes.append("Keep the electronics sealed (a gasket or a coated board).")
        checks.append(
            {
                "name": "In the wet",
                "ok": not rusty,
                "detail": "nothing rusts"
                if not rusty
                else f"rusts: {', '.join(rusty)}",
            }
        )

    # Does it float?
    outer = casing or [c for c in components if c.role == "structure"]
    envelope = sum(_enclosed(c) for c in outer)
    if envelope > 0:
        density = total / envelope
        notes.append(
            f"Floats in water (about {density:.2f} g/cm³ overall)."
            if density < 1
            else f"Sinks in water (about {density:.2f} g/cm³ overall)."
        )

    works = all(bool(item.get("ok")) for item in checks) if checks else True
    return {
        "name": name.strip()[:80] or "My design",
        "wet": wet,
        "series": series,
        "components": rows,
        "electronics": electronics,
        "mass_g": round(total, 1),
        "materials": [
            {
                "id": material_id,
                "name": found.name,
                "colour": found.colour,
                "finish": finish(found),
                "grams": round(grams, 1),
                "share_pct": round(grams / total * 100, 1) if total else 0.0,
            }
            for material_id, grams in sorted(
                by_material.items(), key=lambda item: item[1], reverse=True
            )
            if (found := materials.find(material_id)) is not None
        ],
        "checks": checks,
        "works": works,
        "verdict": "Would work" if works and not warnings else "Needs changes",
        "warnings": warnings,
        "notes": notes,
        "estimate": (
            "Estimates from handbook values for a sketch: straight loads only "
            "(no bending or buckling), heat by still air, no joints or welds."
        ),
    }


def _enclosed(component: Component) -> float:
    """The space a casing or frame takes up (its outer volume, cm³)."""
    w, h, d = component.size_mm
    if component.shape in {"rod", "cylinder", "tube"}:
        return math.pi * (w / 2) ** 2 * h / 1000 * component.count
    if component.shape == "sphere":
        return 4 / 3 * math.pi * (w / 2) ** 3 / 1000 * component.count
    return w * h * d / 1000 * component.count
