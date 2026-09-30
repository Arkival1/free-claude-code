"""Mix chemicals and see what really happens.

A rule-based simulator built on textbook chemistry: acids and bases
neutralise, carbonates fizz, metals give off hydrogen, ions that make an
insoluble salt precipitate in its real colour, catalysts split peroxide,
indicators change colour with pH, and every reaction's heat warms or cools
the beaker. Amounts are in millilitres for liquids and grams for solids.
Anything the rules don't cover is listed so an AI can predict it instead.
"""

import math
import re
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field

from . import LabData
from .chemicals import HAZARDS, Chemical, resolve
from .elements import FLAME_COLOURS
from .formula import FormulaError, molar_mass, pretty

ROOM_C = 20.0
GAS_ML_PER_MOL = 24_000
DEFAULT_ML = 20.0
DEFAULT_G = 2.0
MAX_ITEMS = 12
MAX_AMOUNT = 2_000.0

# Grams that dissolve in 100 mL of water at room temperature.
SOLUBILITY = {
    "NaCl": 36,
    "KCl": 34,
    "CaCl2": 74,
    "MgSO4": 35,
    "Na2SO4": 28,
    "NH4NO3": 150,
    "NH4Cl": 37,
    "KNO3": 32,
    "NaHCO3": 9.6,
    "Na2CO3": 30,
    "C12H22O11": 200,
    "C6H12O6": 91,
    "C6H8O7": 59,
    "C6H8O6": 33,
    "NaOH": 111,
    "H3BO3": 4.7,
    "Na2B4O7·10H2O": 5.1,
    "CuSO4·5H2O": 32,
    "LiCl": 83,
    "SrCl2": 54,
    "NaF": 4,
    "C2H2O4": 14,
    "C7H6O3": 0.2,
}

ION_COLOURS: dict[str, tuple[str, float]] = {
    # ion: (colour, how strongly 1 mol/L tints the water)
    "Cu2+": ("#2f80ff", 3.0),
    "Fe3+": ("#d99a1e", 12.0),
    "Fe2+": ("#9fd18a", 2.0),
    "Ni2+": ("#3fae5a", 5.0),
    "Co2+": ("#e0608f", 6.0),
    "MnO4-": ("#7b1fa2", 500.0),
    "CrO42-": ("#f2c500", 40.0),
    "Cu(NH3)42+": ("#1036d6", 40.0),
    "I3-": ("#a35a12", 300.0),
    "MnO42-": ("#2e9e3e", 300.0),
}

_SINGLE = {"NH4+", "NO3-", "MnO4-", "HCO3-", "OCl-", "CH3COO-"}

# Insoluble salts: (cation, per, anion, per, formula, name, colour).
PRECIPITATES: tuple[tuple[str, int, str, int, str, str, str], ...] = (
    ("Ag+", 1, "Cl-", 1, "AgCl", "silver chloride", "#f4f4f4"),
    ("Ag+", 1, "Br-", 1, "AgBr", "silver bromide", "#f1e9c8"),
    ("Ag+", 1, "I-", 1, "AgI", "silver iodide", "#f3e27a"),
    ("Ag+", 2, "CrO42-", 1, "Ag2CrO4", "silver chromate", "#a8341c"),
    ("Ag+", 2, "S2-", 1, "Ag2S", "silver sulfide", "#1b1b1b"),
    ("Ag+", 3, "PO43-", 1, "Ag3PO4", "silver phosphate", "#f2d33c"),
    ("Ag+", 2, "CO32-", 1, "Ag2CO3", "silver carbonate", "#efe6b0"),
    ("Ag+", 2, "OH-", 2, "Ag2O", "silver oxide", "#5a3a22"),
    ("Pb2+", 1, "I-", 2, "PbI2", "lead(II) iodide", "#ffd400"),
    ("Pb2+", 1, "CrO42-", 1, "PbCrO4", "lead(II) chromate", "#ffc400"),
    ("Pb2+", 1, "S2-", 1, "PbS", "lead(II) sulfide", "#1b1b1b"),
    ("Pb2+", 1, "SO42-", 1, "PbSO4", "lead(II) sulfate", "#f7f7f7"),
    ("Pb2+", 1, "Cl-", 2, "PbCl2", "lead(II) chloride", "#f7f7f7"),
    ("Pb2+", 1, "Br-", 2, "PbBr2", "lead(II) bromide", "#f7f7f2"),
    ("Pb2+", 1, "CO32-", 1, "PbCO3", "lead(II) carbonate", "#f7f7f7"),
    ("Pb2+", 1, "OH-", 2, "Pb(OH)2", "lead(II) hydroxide", "#f5f5f5"),
    ("Ba2+", 1, "SO42-", 1, "BaSO4", "barium sulfate", "#fbfbfb"),
    ("Ba2+", 1, "CrO42-", 1, "BaCrO4", "barium chromate", "#f5e04a"),
    ("Ba2+", 1, "CO32-", 1, "BaCO3", "barium carbonate", "#f7f7f7"),
    ("Ba2+", 3, "PO43-", 2, "Ba3(PO4)2", "barium phosphate", "#f7f7f7"),
    ("Cu2+", 1, "S2-", 1, "CuS", "copper(II) sulfide", "#111111"),
    ("Cu2+", 1, "OH-", 2, "Cu(OH)2", "copper(II) hydroxide", "#6fb7ff"),
    ("Cu2+", 1, "CO32-", 1, "CuCO3", "copper(II) carbonate", "#4fb39a"),
    ("Cu2+", 3, "PO43-", 2, "Cu3(PO4)2", "copper(II) phosphate", "#5aa9e6"),
    ("Fe3+", 1, "OH-", 3, "Fe(OH)3", "iron(III) hydroxide", "#a0461c"),
    ("Fe3+", 1, "PO43-", 1, "FePO4", "iron(III) phosphate", "#e8d9a0"),
    ("Fe2+", 1, "S2-", 1, "FeS", "iron(II) sulfide", "#141414"),
    ("Fe2+", 1, "OH-", 2, "Fe(OH)2", "iron(II) hydroxide", "#6a8f4e"),
    ("Ni2+", 1, "OH-", 2, "Ni(OH)2", "nickel(II) hydroxide", "#6fcf6f"),
    ("Ni2+", 1, "S2-", 1, "NiS", "nickel(II) sulfide", "#151515"),
    ("Co2+", 1, "OH-", 2, "Co(OH)2", "cobalt(II) hydroxide", "#d97aa0"),
    ("Zn2+", 1, "S2-", 1, "ZnS", "zinc sulfide", "#fafafa"),
    ("Zn2+", 1, "OH-", 2, "Zn(OH)2", "zinc hydroxide", "#f7f7f7"),
    ("Zn2+", 1, "CO32-", 1, "ZnCO3", "zinc carbonate", "#f7f7f7"),
    ("Al3+", 1, "OH-", 3, "Al(OH)3", "aluminium hydroxide", "#f2f4f5"),
    ("Mg2+", 1, "OH-", 2, "Mg(OH)2", "magnesium hydroxide", "#f7f7f7"),
    ("Mg2+", 1, "CO32-", 1, "MgCO3", "magnesium carbonate", "#f7f7f7"),
    ("Ca2+", 1, "CO32-", 1, "CaCO3", "calcium carbonate", "#fbfbfb"),
    ("Ca2+", 3, "PO43-", 2, "Ca3(PO4)2", "calcium phosphate", "#fbfbfb"),
    ("Ca2+", 1, "F-", 2, "CaF2", "calcium fluoride", "#fbfbfb"),
    ("Sr2+", 1, "SO42-", 1, "SrSO4", "strontium sulfate", "#fbfbfb"),
    ("Sr2+", 1, "CO32-", 1, "SrCO3", "strontium carbonate", "#fbfbfb"),
)

# Metal: (ion it becomes, electrons, heat per mole with acid in kJ).
METALS: dict[str, tuple[str, int, float]] = {
    "K": ("K+", 1, 196.0),
    "Na": ("Na+", 1, 184.0),
    "Li": ("Li+", 1, 222.0),
    "Ca": ("Ca2+", 2, 415.0),
    "Mg": ("Mg2+", 2, 467.0),
    "Al": ("Al3+", 3, 531.0),
    "Zn": ("Zn2+", 2, 153.0),
    "Fe": ("Fe2+", 2, 89.0),
    "Ni": ("Ni2+", 2, 64.0),
    "Sn": ("Sn2+", 2, 60.0),
    "Pb": ("Pb2+", 2, 0.0),
    "Cu": ("Cu2+", 2, 0.0),
    "Ag": ("Ag+", 1, 0.0),
    "Au": ("Au3+", 3, 0.0),
}
ACTIVITY = (
    "K",
    "Na",
    "Li",
    "Ca",
    "Mg",
    "Al",
    "Zn",
    "Fe",
    "Ni",
    "Sn",
    "Pb",
    "Cu",
    "Ag",
    "Au",
)
_METAL_ION_NAMES = {
    "Cu2+": ("Cu", "copper", "#c46a3a"),
    "Ag+": ("Ag", "silver", "#dfe3e8"),
    "Pb2+": ("Pb", "lead", "#6f7780"),
    "Au3+": ("Au", "gold", "#f5c542"),
    "Ni2+": ("Ni", "nickel", "#9ca3a8"),
    "Sn2+": ("Sn", "tin", "#bfc5c9"),
    "Fe2+": ("Fe", "iron", "#5d5d5d"),
}

SUPERSCRIPT = str.maketrans("0123456789+-", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻")


class LabError(ValueError):
    """A mix that can't be simulated as asked."""


def ion_charge(ion: str) -> tuple[str, int]:
    """'SO42-' → ('SO4', -2); 'NH4+' → ('NH4', 1)."""
    sign = 1 if ion.endswith("+") else -1
    body = ion[:-1]
    if ion in _SINGLE or not body[-1:].isdigit() or body.endswith(")"):
        return body, sign
    found = re.match(r"^(.*?[A-Za-z)\]])(\d)$", body)
    if found and (found.group(1)[-1].isalpha() or found.group(1)[-1] in ")]"):
        return found.group(1), sign * int(found.group(2))
    return body, sign


def ion_pretty(ion: str) -> str:
    body, charge = ion_charge(ion)
    size = "" if abs(charge) == 1 else str(abs(charge))
    return pretty(body) + (size + ("+" if charge > 0 else "-")).translate(SUPERSCRIPT)


def _hex(colour: str) -> tuple[int, int, int]:
    value = colour.lstrip("#")
    if len(value) == 3:
        value = "".join(char * 2 for char in value)
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def blend(colours: list[tuple[str, float]]) -> tuple[str, float]:
    """Mix tints by weight: the colour and how opaque the mix looks."""
    weighted = [(rgb, weight) for rgb, weight in colours if weight > 0]
    if not weighted:
        return "#e3f2ff", 0.12
    total = sum(weight for _, weight in weighted)
    channels = [
        round(sum(_hex(rgb)[index] * weight for rgb, weight in weighted) / total)
        for index in range(3)
    ]
    opacity = min(0.95, 0.12 + total)
    return "#{:02x}{:02x}{:02x}".format(*channels), round(opacity, 2)


@dataclass
class Portion:
    chemical: Chemical
    amount: float
    unit: str

    @property
    def grams(self) -> float:
        if self.unit == "g":
            return self.amount
        return self.amount * self.chemical.density

    @property
    def moles(self) -> float:
        """Moles of the chemical itself (the solute, for a stock solution)."""
        if self.chemical.state == "solution":
            return self.chemical.concentration * self.amount / 1000
        mass = self.chemical.molar_mass
        return self.grams / mass if mass else 0.0

    @property
    def water_ml(self) -> float:
        chemical = self.chemical
        if chemical.id == "water" or chemical.state == "solution":
            return self.amount
        if chemical.state == "liquid" and chemical.kind in {
            "mixture",
            "household",
            "indicator",
        }:
            return self.amount * 0.9
        if chemical.id in {"aloe-vera", "milk"}:
            return self.amount * 0.9
        return 0.0


@dataclass
class Mix:
    portions: list[Portion]
    heat: bool = False
    flame: bool = False
    ions: defaultdict[str, float] = field(default_factory=lambda: defaultdict(float))
    h: float = 0.0
    oh: float = 0.0
    weak_acids: list[dict[str, float]] = field(default_factory=list)
    weak_bases: list[dict[str, float]] = field(default_factory=list)
    neutral_shift: float = 0.0
    solids: dict[str, LabData] = field(default_factory=dict)
    heat_kj: float = 0.0
    reactions: list[dict[str, str]] = field(default_factory=list)
    observations: list[str] = field(default_factory=list)
    hazards: list[dict[str, str]] = field(default_factory=list)
    products: dict[str, LabData] = field(default_factory=dict)
    precipitates: list[LabData] = field(default_factory=list)
    gases: dict[str, LabData] = field(default_factory=dict)
    tints: list[tuple[str, float]] = field(default_factory=list)
    colour_steps: list[str] = field(default_factory=list)
    foam: float = 0.0
    special: set[str] = field(default_factory=set)
    unknown: list[str] = field(default_factory=list)

    # ------------------------------------------------------------ bookkeeping
    @property
    def water_ml(self) -> float:
        return sum(portion.water_ml for portion in self.portions)

    @property
    def litres(self) -> float:
        return max(self.water_ml, 1.0) / 1000

    @property
    def wet(self) -> bool:
        return self.water_ml > 0.5

    def tagged(self, tag: str) -> list[Portion]:
        return [p for p in self.portions if tag in p.chemical.tags]

    def has(self, *ids: str) -> bool:
        return any(p.chemical.id in ids for p in self.portions)

    def react(self, equation: str, kind: str, note: str = "") -> None:
        entry = {"equation": equation, "kind": kind, "note": note}
        if entry not in self.reactions:
            self.reactions.append(entry)

    def see(self, text: str) -> None:
        if text not in self.observations:
            self.observations.append(text)

    def warn(self, level: str, text: str) -> None:
        entry = {"level": level, "text": text}
        if entry not in self.hazards:
            self.hazards.append(entry)

    def make(self, formula: str, name: str, moles: float, state: str) -> None:
        if moles <= 0:
            return
        entry = self.products.setdefault(
            formula,
            {"formula": formula, "name": name, "moles": 0.0, "state": state},
        )
        entry["moles"] = float(str(entry["moles"])) + moles

    def gas(self, formula: str, name: str, moles: float, colour: str) -> None:
        if moles <= 0:
            return
        entry = self.gases.setdefault(
            formula, {"formula": formula, "name": name, "moles": 0.0, "colour": colour}
        )
        entry["moles"] = float(str(entry["moles"])) + moles
        self.make(formula, name, moles, "gas")


# ------------------------------------------------------------------ the mix


def simulate(
    items: list[LabData],
    *,
    heat: bool = False,
    flame: bool = False,
    extra: Mapping[str, Chemical] | None = None,
) -> LabData:
    """What happens when these go in one beaker (and are heated, or flamed)."""
    if not items:
        raise LabError("Add something to the beaker first.")
    if len(items) > MAX_ITEMS:
        raise LabError(f"The beaker holds up to {MAX_ITEMS} things at once.")
    mix = Mix(portions=[], heat=heat, flame=flame)
    for item in items:
        wanted = str(item.get("id") or item.get("name") or "").strip()
        chemical = (extra or {}).get(wanted.lower()) or resolve(wanted)
        if chemical is None:
            mix.unknown.append(wanted)
            continue
        solid = chemical.state == "solid"
        raw = item.get("amount")
        amount = (
            float(raw)
            if isinstance(raw, int | float) and not isinstance(raw, bool)
            else (DEFAULT_G if solid else DEFAULT_ML)
        )
        if not 0 < amount <= MAX_AMOUNT:
            raise LabError(f"Use between 0 and {MAX_AMOUNT:g} of {chemical.name}.")
        mix.portions.append(Portion(chemical, amount, "g" if solid else "mL"))
    if not mix.portions:
        return _result(mix)
    _dissolve(mix)
    _very_active_metals(mix)
    _carbonates(mix)
    _metals_in_acid(mix)
    _neutralise(mix)
    _displacement(mix)
    _complexes(mix)
    _precipitate(mix)
    _redox(mix)
    _organics(mix)
    _safety(mix)
    _heating(mix)
    return _result(mix)


def _dissolve(mix: Mix) -> None:
    for portion in mix.portions:
        chemical = portion.chemical
        moles = portion.moles
        if "insoluble" in chemical.tags or chemical.kind in {"metal", "oil"}:
            if chemical.state == "solid":
                mix.solids[chemical.id] = {
                    "name": chemical.name,
                    "colour": chemical.colour,
                    "grams": portion.grams,
                    "formula": chemical.formula,
                }
            continue
        if chemical.state == "solid":
            if not mix.wet:
                mix.solids[chemical.id] = {
                    "name": chemical.name,
                    "colour": chemical.colour,
                    "grams": portion.grams,
                    "formula": chemical.formula,
                }
                continue
            limit = SOLUBILITY.get(chemical.formula)
            acid_eats_it = "carbonate" in chemical.tags and any(
                other.chemical.acid for other in mix.portions
            )
            if limit is not None and not acid_eats_it:
                fits = limit * mix.water_ml / 100
                if portion.grams > fits * 1.02:
                    left = portion.grams - fits
                    mix.see(
                        f"Only {fits:.3g} g of {chemical.name.lower()} dissolves in "
                        f"{mix.water_ml:.0f} mL: the water is saturated and "
                        f"{left:.3g} g sits on the bottom."
                    )
                    mix.solids[chemical.id] = {
                        "name": chemical.name,
                        "colour": chemical.colour,
                        "grams": left,
                        "formula": chemical.formula,
                    }
                    moles *= fits / portion.grams
            if chemical.dissolve_heat:
                mix.heat_kj += chemical.dissolve_heat * moles
                mix.see(
                    f"The {chemical.name.lower()} {'warms' if chemical.dissolve_heat > 0 else 'cools'} "
                    "the water as it dissolves."
                )
            elif chemical.kind in {"salt", "sugar"} and moles:
                mix.see(f"The {chemical.name.lower()} dissolves.")
        for ion, count in chemical.ions:
            if ion not in {"H+", "OH-"}:
                mix.ions[ion] += moles * count
        if chemical.acid:
            strength, pka, protons = chemical.acid
            if strength == "strong":
                mix.h += moles * protons
            else:
                mix.weak_acids.append(
                    {"pka": pka, "left": moles * protons, "conj": 0.0}
                )
        if chemical.base and "carbonate" not in chemical.tags:
            strength, pkb, hydroxides = chemical.base
            if strength == "strong":
                mix.oh += moles * hydroxides
            else:
                mix.weak_bases.append(
                    {"pkb": pkb, "left": moles * hydroxides, "conj": 0.0}
                )
        if chemical.id == "copper-sulfate-crystals":
            mix.special.add("hydrated-blue")


def _very_active_metals(mix: Mix) -> None:
    for portion in mix.tagged("very-active-metal"):
        symbol = portion.chemical.formula
        if symbol not in METALS or not (mix.wet or mix.h):
            continue
        ion, electrons, heat = METALS[symbol]
        moles = portion.moles
        mix.solids.pop(portion.chemical.id, None)
        mix.ions[ion] += moles
        from_acid = min(mix.h, moles * electrons)
        mix.h -= from_acid
        mix.oh += moles * electrons - from_acid
        mix.heat_kj += heat * moles
        mix.gas("H2", "hydrogen", moles * electrons / 2, "#ffffff")
        name = portion.chemical.name.split()[0].lower()
        if electrons == 1:
            mix.react(
                f"2{symbol}(s) + 2H₂O(l) → 2{ion_pretty(ion)}(aq) + 2OH⁻(aq) + H₂↑",
                "metal + water",
            )
        else:
            mix.react(
                f"{symbol}(s) + 2H₂O(l) → {ion_pretty(ion)}(aq) + 2OH⁻(aq) + H₂↑",
                "metal + water",
            )
        mix.special.add("violent")
        if symbol == "K":
            mix.see("The potassium whizzes round, bursts into a lilac flame and pops.")
        elif symbol == "Na":
            mix.see(
                "The sodium melts into a silvery ball, fizzes and skates across the water."
            )
        elif symbol == "Li":
            mix.see("The lithium fizzes steadily and floats.")
        else:
            mix.see(f"The {name} sinks and bubbles steadily; the water turns cloudy.")
        mix.warn(
            "danger",
            f"{portion.chemical.name} reacts violently with water: hydrogen can ignite "
            "and hot lye spits. Only tiny pieces, behind a shield, by a teacher.",
        )


def _take_acid(mix: Mix, wanted: float) -> tuple[float, bool]:
    """Use up to `wanted` moles of H+, strong acid first. Returns (got, weak)."""
    got = min(mix.h, wanted)
    mix.h -= got
    weak = False
    for acid in sorted(mix.weak_acids, key=lambda a: a["pka"]):
        if got >= wanted - 1e-12:
            break
        take = min(acid["left"], wanted - got)
        if take > 0:
            acid["left"] -= take
            acid["conj"] += take
            got += take
            weak = True
    return got, weak


def _carbonates(mix: Mix) -> None:
    for portion in mix.tagged("carbonate"):
        formula = portion.chemical.formula
        moles = portion.moles
        if "HCO3" in formula:
            per, anion = 1, "HCO3-"
        else:
            per, anion = 2, "CO32-"
        acid_left = mix.h + sum(a["left"] for a in mix.weak_acids)
        if acid_left <= 0:
            continue
        reacted_h, _ = _take_acid(mix, moles * per)
        reacted = reacted_h / per
        if reacted <= 0:
            continue
        if anion in mix.ions:
            mix.ions[anion] = max(0.0, mix.ions[anion] - reacted)
        if formula == "CaCO3":
            mix.ions["Ca2+"] += reacted
            solid = mix.solids.get(portion.chemical.id)
            if solid:
                solid["grams"] = max(
                    0.0, float(str(solid["grams"])) - reacted * molar_mass("CaCO3")
                )
                if float(str(solid["grams"])) < 0.01:
                    mix.solids.pop(portion.chemical.id)
                    mix.see("The chalk fizzes away until it has all dissolved.")
                else:
                    mix.see("The chalk fizzes and gets smaller.")
            mix.react(
                "CaCO₃(s) + 2H⁺(aq) → Ca²⁺(aq) + CO₂↑ + H₂O(l)", "acid + carbonate"
            )
            mix.heat_kj += 15 * reacted
        elif per == 1:
            mix.react("HCO₃⁻(aq) + H⁺(aq) → CO₂↑ + H₂O(l)", "acid + carbonate")
            mix.heat_kj -= 11.8 * reacted
            mix.see("It fizzes up at once, and the beaker feels a little colder.")
        else:
            mix.react("CO₃²⁻(aq) + 2H⁺(aq) → CO₂↑ + H₂O(l)", "acid + carbonate")
            mix.heat_kj += 27 * reacted
        mix.gas("CO2", "carbon dioxide", reacted, "#ffffff")
        mix.make("H2O", "water", reacted, "liquid")


def _metals_in_acid(mix: Mix) -> None:
    for portion in mix.portions:
        chemical = portion.chemical
        symbol = chemical.formula
        if chemical.kind != "metal" or "very-active-metal" in chemical.tags:
            continue
        if symbol == "Cu" and mix.ions.get("NO3-", 0) and mix.h > 0:
            used = min(portion.moles, mix.h * 3 / 8)
            mix.h -= used * 8 / 3
            mix.ions["Cu2+"] += used
            mix.gas(
                "NO",
                "nitrogen monoxide (turns brown NO₂ in air)",
                used * 2 / 3,
                "#b5651d",
            )
            mix.react(
                "3Cu(s) + 8H⁺ + 2NO₃⁻ → 3Cu²⁺ + 2NO↑ + 4H₂O",
                "metal + nitric acid",
                "Nitric acid is an oxidiser: it dissolves copper, which other acids can't.",
            )
            mix.see("The copper dissolves, the liquid turns blue and brown fumes rise.")
            mix.warn("danger", "Nitrogen dioxide fumes are toxic: fume cupboard only.")
            _shrink(mix, portion, used)
            continue
        if "active-metal" not in chemical.tags or symbol not in METALS:
            if (
                chemical.kind == "metal"
                and (mix.h > 0 or mix.weak_acids)
                and symbol in {"Cu", "Ag", "Au"}
            ):
                mix.see(
                    f"The {chemical.name.split()[0].lower()} doesn't react: it is below "
                    "hydrogen in the reactivity series."
                )
            continue
        ion, electrons, heat = METALS[symbol]
        if mix.h <= 0 and not any(a["left"] > 0 for a in mix.weak_acids):
            continue
        got, weak = _take_acid(mix, portion.moles * electrons)
        used = got / electrons
        if used <= 0:
            continue
        mix.ions[ion] += used
        mix.heat_kj += heat * used
        mix.gas("H2", "hydrogen", got / 2, "#ffffff")
        mix.react(
            {
                1: f"2{symbol}(s) + 2H⁺ → 2{ion_pretty(ion)} + H₂↑",
                2: f"{symbol}(s) + 2H⁺ → {ion_pretty(ion)} + H₂↑",
                3: f"2{symbol}(s) + 6H⁺ → 2{ion_pretty(ion)} + 3H₂↑",
            }[electrons],
            "metal + acid",
        )
        speed = "slowly" if weak or symbol in {"Fe", "Sn", "Ni", "Pb"} else "quickly"
        if symbol == "Al" and not weak:
            mix.see(
                "The aluminium waits a moment (its oxide skin) and then fizzes hard."
            )
        else:
            mix.see(
                f"The {chemical.name.split()[0].lower()} fizzes {speed}, giving off hydrogen."
            )
        if symbol == "Fe":
            mix.see("The liquid turns pale green (iron(II) ions).")
        _shrink(mix, portion, used)


def _shrink(mix: Mix, portion: Portion, used: float) -> None:
    solid = mix.solids.get(portion.chemical.id)
    if not solid:
        return
    grams = float(str(solid["grams"])) - used * portion.chemical.molar_mass
    if grams < 0.005:
        mix.solids.pop(portion.chemical.id)
        mix.see(
            f"The {portion.chemical.name.split()[0].lower()} is used up completely."
        )
    else:
        solid["grams"] = grams


def _neutralise(mix: Mix) -> None:
    both = min(mix.h, mix.oh)
    if both > 0:
        mix.h -= both
        mix.oh -= both
        mix.heat_kj += 57.3 * both
        mix.make("H2O", "water", both, "liquid")
        mix.react(
            "H⁺(aq) + OH⁻(aq) → H₂O(l)",
            "neutralisation",
            "Acid and alkali cancel out into water and a salt.",
        )
    if mix.oh > 0:
        for acid in mix.weak_acids:
            take = min(acid["left"], mix.oh)
            if take > 0:
                acid["left"] -= take
                acid["conj"] += take
                mix.oh -= take
                mix.heat_kj += 55.0 * take
                mix.make("H2O", "water", take, "liquid")
                mix.react(
                    "HA(aq) + OH⁻(aq) → A⁻(aq) + H₂O(l)",
                    "neutralisation",
                    "A weak acid is neutralised.",
                )
    if mix.h > 0:
        for base in mix.weak_bases:
            take = min(base["left"], mix.h)
            if take > 0:
                base["left"] -= take
                base["conj"] += take
                mix.h -= take
                mix.heat_kj += 52.0 * take
                mix.react(
                    "B(aq) + H⁺(aq) → BH⁺(aq)",
                    "neutralisation",
                    "A weak base is neutralised.",
                )
    if mix.weak_bases and mix.weak_acids:
        for base in mix.weak_bases:
            for acid in mix.weak_acids:
                take = min(base["left"], acid["left"])
                if take > 0:
                    base["left"] -= take
                    acid["left"] -= take
                    base["conj"] += take
                    acid["conj"] += take
                    mix.heat_kj += 50.0 * take


def _displacement(mix: Mix) -> None:
    for portion in mix.portions:
        symbol = portion.chemical.formula
        if portion.chemical.kind != "metal" or symbol not in ACTIVITY:
            continue
        if (
            portion.chemical.id not in mix.solids
            or "very-active-metal" in portion.chemical.tags
        ):
            continue
        rank = ACTIVITY.index(symbol)
        own_ion, own_e, _ = METALS[symbol]
        for ion, (metal, name, colour) in _METAL_ION_NAMES.items():
            if metal not in ACTIVITY or ACTIVITY.index(metal) <= rank:
                continue
            present = mix.ions.get(ion, 0.0)
            if present <= 1e-9:
                continue
            ion_e = METALS[metal][1]
            solid = mix.solids.get(portion.chemical.id)
            if not solid:
                break
            have = float(str(solid["grams"])) / portion.chemical.molar_mass
            used = min(have, present * ion_e / own_e)
            freed = used * own_e / ion_e
            mix.ions[ion] -= freed
            mix.ions[own_ion] += used
            _shrink(mix, portion, used)
            mix.solids[f"deposit-{metal}"] = {
                "name": f"{name} metal",
                "colour": colour,
                "grams": freed * molar_mass(metal),
                "formula": metal,
            }
            mix.make(metal, name, freed, "solid")
            mix.heat_kj += 30 * used
            lcm = math.lcm(own_e, ion_e)
            ours, theirs = lcm // own_e, lcm // ion_e
            mix.react(
                f"{_n(ours)}{symbol}(s) + {_n(theirs)}{ion_pretty(ion)}(aq) → "
                f"{_n(ours)}{ion_pretty(own_ion)}(aq) + {_n(theirs)}{metal}(s)",
                "displacement",
                f"{portion.chemical.name.split()[0]} is more reactive than {name}, so it pushes {name} out.",
            )
            if metal == "Ag":
                mix.see(
                    "Shiny silver crystals grow on the metal like a tree, and the liquid turns blue."
                )
            elif metal == "Cu":
                mix.see(
                    "A pink-brown coat of copper forms on the metal and the blue colour fades."
                )
            else:
                mix.see(
                    f"A coat of {name} forms on the {portion.chemical.name.split()[0].lower()}."
                )


def _n(count: int) -> str:
    return "" if count == 1 else str(count)


def _complexes(mix: Mix) -> None:
    ammonia = sum(p.moles for p in mix.tagged("ammonia"))
    copper = mix.ions.get("Cu2+", 0.0)
    if ammonia and copper and ammonia >= 4 * copper:
        mix.ions["Cu2+"] = 0.0
        mix.ions["Cu(NH3)42+"] += copper
        mix.react(
            "Cu²⁺(aq) + 4NH₃(aq) → [Cu(NH₃)₄]²⁺(aq)",
            "complex",
            "A pale blue precipitate forms first, then dissolves in more ammonia.",
        )
        mix.see(
            "A pale blue cloud forms, then dissolves into a deep royal-blue liquid."
        )
        mix.colour_steps = ["#6fb7ff", "#1036d6"]


def _precipitate(mix: Mix) -> None:
    if not mix.wet:
        return
    mix.ions["OH-"] = mix.oh
    for cation, per_c, anion, per_a, formula, name, colour in PRECIPITATES:
        have_c = mix.ions.get(cation, 0.0)
        have_a = mix.ions.get(anion, 0.0)
        moles = min(have_c / per_c, have_a / per_a)
        if moles <= 1e-7:
            continue
        mix.ions[cation] -= moles * per_c
        mix.ions[anion] -= moles * per_a
        grams = moles * molar_mass(formula)
        mix.precipitates.append(
            {
                "formula": formula,
                "name": name,
                "colour": colour,
                "grams": round(grams, 4),
            }
        )
        mix.make(formula, name, moles, "solid")
        left = f"{per_c if per_c > 1 else ''}{ion_pretty(cation)}(aq)"
        right = f"{per_a if per_a > 1 else ''}{ion_pretty(anion)}(aq)"
        mix.react(
            f"{left} + {right} → {pretty(formula)}(s)",
            "precipitation",
            f"{name.capitalize()} doesn't dissolve in water.",
        )
        described = _colour_word(colour)
        if formula == "PbI2":
            mix.see(
                "A brilliant yellow cloud of lead iodide swirls through the liquid ('golden rain')."
            )
        else:
            mix.see(f"A {described} precipitate of {name} forms and slowly settles.")
    mix.oh = mix.ions.pop("OH-", 0.0)
    # Hydroxides of zinc and aluminium dissolve again in plenty of alkali.
    for entry in mix.precipitates:
        if entry["formula"] in {"Zn(OH)2", "Al(OH)3"} and mix.oh > 4 * float(
            str(entry["grams"])
        ) / molar_mass(str(entry["formula"])):
            entry["redissolved"] = True
            mix.see(
                f"With more alkali the white {entry['name']} dissolves again (it is amphoteric)."
            )
    mix.precipitates = [p for p in mix.precipitates if not p.get("redissolved")]
    soap = mix.has("sodium-stearate")
    hard = mix.ions.get("Ca2+", 0) + mix.ions.get("Mg2+", 0)
    if soap and hard > 1e-5:
        mix.precipitates.append(
            {
                "formula": "Ca(C18H35O2)2",
                "name": "soap scum",
                "colour": "#f3efe2",
                "grams": round(hard * 606, 3),
            }
        )
        mix.react(
            "2C₁₇H₃₅COO⁻ + Ca²⁺ → Ca(C₁₇H₃₅COO)₂(s)",
            "precipitation",
            "Hard-water ions turn soap into scum.",
        )
        mix.see("Grey-white scum forms instead of lather: the water is hard.")


def _colour_word(colour: str) -> str:
    red, green, blue = _hex(colour)
    if max(red, green, blue) < 60:
        return "black"
    if min(red, green, blue) > 225:
        return "white"
    if red > 200 and green > 180 and blue < 140:
        return "yellow"
    if red > 150 and green < 110 and blue < 80:
        return "brick-red" if red < 200 else "orange-red"
    if blue > red and blue > green:
        return "blue"
    if green > red and green > blue:
        return "green"
    if red > green and green > blue:
        return "rust-brown" if red < 190 else "cream"
    if red > blue and blue > green:
        return "pink"
    return "coloured"


def _redox(mix: Mix) -> None:
    peroxide = mix.tagged("peroxide")
    catalysts = mix.tagged("peroxide-catalyst")
    surfactant = bool(mix.tagged("surfactant"))
    reducers = mix.tagged("reducer")
    bleach = mix.tagged("hypochlorite")
    iodide = mix.ions.get("I-", 0.0)
    acidic = mix.h > 0 or any(a["left"] > 0 for a in mix.weak_acids)
    if peroxide and (catalysts or iodide or mix.heat or bleach):
        moles = sum(p.moles for p in peroxide)
        mix.gas("O2", "oxygen", moles / 2, "#ffffff")
        mix.make("H2O", "water", moles, "liquid")
        mix.heat_kj += 98 * moles
        catalyst = catalysts[0].chemical.name.lower() if catalysts else "heat"
        mix.react(
            "2H₂O₂(aq) → 2H₂O(l) + O₂↑",
            "decomposition",
            f"The {catalyst} speeds up the splitting of hydrogen peroxide.",
        )
        if surfactant:
            mix.foam = 1.0
            mix.special.add("elephant-toothpaste")
            mix.see(
                "A huge column of foam erupts out of the beaker ('elephant toothpaste'), steaming warm."
            )
        else:
            mix.see("It fizzes hard, releasing oxygen: a glowing splint would relight.")
        if iodide:
            mix.tints.append(("#c6862a", 0.25))
            mix.see("The foam is tinted yellow-brown by a little iodine.")
        if moles > 0.05:
            mix.warn("warning", "Strong peroxide decomposes fast and hot: stand back.")
    if bleach:
        if mix.h > 0 or acidic:
            mix.gas("Cl2", "chlorine", sum(p.moles for p in bleach) * 0.5, "#c8e05a")
            mix.react("OCl⁻ + Cl⁻ + 2H⁺ → Cl₂↑ + H₂O", "redox")
            mix.warn(
                "danger", "Bleach + acid releases toxic chlorine gas. Never mix them."
            )
            mix.see("A sharp-smelling yellow-green gas comes off.")
        if mix.tagged("ammonia"):
            mix.gas(
                "NH2Cl", "chloramine", sum(p.moles for p in bleach) * 0.5, "#e8f4ff"
            )
            mix.react("NH₃ + OCl⁻ → NH₂Cl + OH⁻", "redox")
            mix.warn(
                "danger", "Bleach + ammonia makes toxic chloramine gas. Never mix them."
            )
        if mix.has("ethanol", "acetone", "isopropanol"):
            mix.warn(
                "danger",
                "Bleach + alcohol or acetone can make chloroform and other toxic chemicals.",
            )
            mix.react("C₃H₆O + 3OCl⁻ → CHCl₃ + CH₃COO⁻ + 2OH⁻", "haloform")
        if iodide:
            mix.tints.append(("#8a4b0f", 0.5))
            mix.special.add("iodine")
            mix.react("OCl⁻ + 2I⁻ + H₂O → I₂ + Cl⁻ + 2OH⁻", "redox")
        if any(
            p.chemical.kind in {"indicator"} or p.chemical.roles == ("colour",)
            for p in mix.portions
        ):
            mix.special.add("bleached")
            mix.see("The colour fades away: bleach destroys dyes.")
    if iodide and peroxide and acidic:
        mix.special.add("iodine")
        mix.react("H₂O₂ + 2I⁻ + 2H⁺ → I₂ + 2H₂O", "redox")
        mix.see("The liquid slowly turns yellow, then brown, as iodine forms.")
    if mix.tagged("iodine"):
        mix.special.add("iodine")
    if "iodine" in mix.special and reducers:
        mix.special.discard("iodine")
        mix.react("I₂ + 2S₂O₃²⁻ → 2I⁻ + S₄O₆²⁻  (or vitamin C)", "redox")
        mix.see(
            "The brown iodine colour vanishes: it has been reduced to colourless iodide."
        )
    if "iodine" in mix.special:
        if mix.tagged("starch"):
            mix.special.add("starch-iodine")
            mix.react("I₂ + starch → blue-black starch-iodine complex", "test")
            mix.see("It turns an intense blue-black: the classic test for starch.")
        else:
            mix.tints.append(("#8a4b0f", 0.6))
    permanganate = mix.ions.get("MnO4-", 0.0)
    if permanganate > 0:
        sugary = bool(mix.tagged("sugar"))
        oxidised = reducers or sugary or peroxide or (mix.tagged("fuel") and mix.wet)
        if oxidised:
            if mix.oh > 0 and sugary:
                mix.ions["MnO4-"] = 0
                mix.colour_steps = ["#7b1fa2", "#3949ab", "#2e9e3e", "#c68a2a"]
                mix.react(
                    "MnO₄⁻ (purple) → MnO₄²⁻ (green) → MnO₂ (brown)",
                    "redox",
                    "The 'chemical chameleon'.",
                )
                mix.see(
                    "The chemical chameleon: purple → blue → green → orange-brown as the sugar is oxidised."
                )
                mix.precipitates.append(
                    {
                        "formula": "MnO2",
                        "name": "manganese dioxide",
                        "colour": "#6b4a2a",
                        "grams": round(permanganate * 87, 4),
                    }
                )
            elif acidic:
                mix.ions["MnO4-"] = 0
                mix.ions["Mn2+"] += permanganate
                mix.react(
                    "MnO₄⁻ + 8H⁺ + 5e⁻ → Mn²⁺ + 4H₂O",
                    "redox",
                    "Permanganate is reduced to almost colourless Mn²⁺.",
                )
                mix.see("The purple colour disappears.")
                mix.colour_steps = ["#7b1fa2", "#e3f2ff"]
                if peroxide:
                    mix.gas("O2", "oxygen", permanganate * 2.5, "#ffffff")
            else:
                mix.ions["MnO4-"] = 0
                mix.precipitates.append(
                    {
                        "formula": "MnO2",
                        "name": "manganese dioxide",
                        "colour": "#5a3d25",
                        "grams": round(permanganate * 87, 4),
                    }
                )
                mix.react("MnO₄⁻ + 2H₂O + 3e⁻ → MnO₂(s) + 4OH⁻", "redox")
                mix.see(
                    "The purple fades and a brown sludge of manganese dioxide forms."
                )
                mix.colour_steps = ["#7b1fa2", "#8d6e63"]


def _organics(mix: Mix) -> None:
    oils = [p for p in mix.tagged("oil") if p.chemical.kind == "oil"]
    alkali = mix.oh
    if oils and alkali > 0:
        oil_moles = sum(p.grams for p in oils) / 885
        soap = min(oil_moles, alkali / 3)
        if soap > 0:
            mix.oh -= soap * 3
            mix.make(
                "C18H33NaO2", "soap (sodium salts of fatty acids)", soap * 3, "solid"
            )
            mix.make("C3H8O3", "glycerin", soap, "liquid")
            mix.react(
                "fat + 3NaOH → 3 soap + glycerin",
                "saponification",
                "Lye splits fats into soap and glycerin.",
            )
            mix.special.add("soap")
            if mix.heat:
                mix.see(
                    "Stirred hot, the oil and lye thicken to 'trace' and turn into soap."
                )
            else:
                mix.see(
                    "The oil and lye slowly turn creamy; the soap sets over 24-48 hours and cures in 4 weeks."
                )
            mix.warn(
                "warning",
                "Lye (sodium hydroxide) burns: gloves and goggles for soap making.",
            )
    if mix.has("pva-glue") and (
        mix.has("borax") or (mix.has("boric-acid") and mix.tagged("carbonate"))
    ):
        mix.special.add("slime")
        mix.make("PVA-borate", "slime (cross-linked PVA)", 0.01, "gel")
        mix.react(
            "PVA chains + B(OH)₄⁻ → cross-linked gel",
            "cross-linking",
            "Borate ions tie the glue's long chains together.",
        )
        mix.see("The glue suddenly stiffens into stretchy, bouncy slime.")
    milk = mix.has("milk")
    if milk and (
        mix.h > 0
        or any(a["pka"] < 5 and a["left"] + a["conj"] > 0 for a in mix.weak_acids)
    ):
        mix.special.add("curdled")
        mix.precipitates.append(
            {
                "formula": "casein",
                "name": "casein curds",
                "colour": "#fffdf0",
                "grams": 0.5,
            }
        )
        mix.see("The milk curdles into white lumps of casein.")
        mix.react("casein (in milk) + H⁺ → casein curds (solid)", "denaturing")
    surfactants = mix.tagged("surfactant")
    if surfactants and mix.wet:
        mix.foam = max(mix.foam, 0.35 if mix.gases else 0.2)
        if mix.gases and "elephant-toothpaste" not in mix.special:
            mix.foam = max(mix.foam, 0.7)
            mix.see("The gas bubbles are trapped in the soap as a thick foam.")
    oily = [p for p in mix.portions if "oil" in p.chemical.tags]
    if oily and mix.wet:
        if (
            surfactants
            or mix.has("emulsifying-wax", "polysorbate-20")
            or "soap" in mix.special
        ):
            mix.special.add("emulsion")
            mix.see("The oil and water mix into a milky emulsion.")
        else:
            mix.special.add("layers")
            mix.see("The oil floats on top in its own layer: oil and water don't mix.")


def _safety(mix: Mix) -> None:
    oxidisers = [
        p
        for p in mix.portions
        if "oxidizer" in p.chemical.hazards and p.chemical.state == "solid"
    ]
    fuels = mix.tagged("fuel")
    if oxidisers and fuels:
        mix.special.add("fire-risk")
        mix.warn(
            "danger",
            f"{oxidisers[0].chemical.name} with {fuels[0].chemical.name.lower()} is a "
            "fire and explosion risk. The Lab won't heat or light it.",
        )
    for portion in mix.portions:
        if "radioactive" in portion.chemical.hazards:
            mix.warn(
                "danger", f"{portion.chemical.name} is radioactive: licensed labs only."
            )
        if portion.chemical.state == "gas" and "toxic" in portion.chemical.hazards:
            mix.warn(
                "danger", f"{portion.chemical.name} gas is toxic: fume cupboard only."
            )


def _heating(mix: Mix) -> None:
    if not (mix.heat or mix.flame):
        return
    if "fire-risk" in mix.special:
        mix.see("Heating stopped: fuel mixed with an oxidiser can burn explosively.")
        return
    if mix.flame:
        _flame(mix)
    if mix.wet and mix.heat:
        mix.see(
            "The liquid is heated to boiling; reactions speed up and water steams off."
        )
        return
    for key, solid in list(mix.solids.items()):
        formula = str(solid["formula"])
        grams = float(str(solid["grams"]))
        if key == "copper-sulfate-crystals":
            moles = grams / molar_mass("CuSO4·5H2O")
            solid.update(
                colour="#f2f2ee", name="anhydrous copper(II) sulfate", formula="CuSO4"
            )
            mix.make("H2O", "steam", moles * 5, "gas")
            mix.react(
                "CuSO₄·5H₂O(s) → CuSO₄(s) + 5H₂O(g)",
                "dehydration",
                "Add water back and it turns blue again.",
            )
            mix.see("The blue crystals crackle, steam off their water and turn white.")
        elif formula == "NaHCO3":
            moles = grams / molar_mass("NaHCO3")
            mix.gas("CO2", "carbon dioxide", moles / 2, "#ffffff")
            mix.make("Na2CO3", "sodium carbonate", moles / 2, "solid")
            mix.react(
                "2NaHCO₃(s) → Na₂CO₃(s) + H₂O(g) + CO₂↑",
                "decomposition",
                "Why baking soda makes cakes rise.",
            )
            mix.see("The powder gives off carbon dioxide and steam.")
        elif formula == "CaCO3" and mix.flame:
            mix.react("CaCO₃(s) → CaO(s) + CO₂↑  (above 840 °C)", "decomposition")
            mix.see("In a hot flame the chalk slowly glows and turns to quicklime.")
        elif formula in {"C12H22O11", "C6H12O6"}:
            mix.colour_steps = ["#ffffff", "#e0a84a", "#8a4a12", "#1b1b1b"]
            mix.react("C₁₂H₂₂O₁₁ → caramel → 12C + 11H₂O", "decomposition")
            mix.see(
                "The sugar melts, turns golden caramel, then black carbon, smelling of burnt toffee."
            )
            solid["colour"] = "#6b3a12"
        elif formula == "NH4Cl":
            mix.react("NH₄Cl(s) ⇌ NH₃(g) + HCl(g)", "decomposition")
            mix.see(
                "White smoke rises and re-forms as a solid on the cool part of the tube."
            )
        elif key in {
            "beeswax",
            "paraffin-wax",
            "soy-wax",
            "shea-butter",
            "coconut-oil",
        }:
            mix.see(f"The {str(solid['name']).lower()} melts into a clear liquid.")
        elif formula == "Mg" and mix.flame:
            mix.special.add("dazzle")
            moles = grams / molar_mass("Mg")
            mix.make("MgO", "magnesium oxide", moles, "solid")
            mix.react("2Mg(s) + O₂ → 2MgO(s)", "combustion")
            mix.see(
                "The magnesium burns with a dazzling white light and leaves white ash."
            )
            mix.warn(
                "warning",
                "Don't look straight at burning magnesium: it can hurt your eyes.",
            )
            mix.heat_kj += 601 * moles
    if mix.has("iron") and mix.has("sulfur"):
        mix.react(
            "Fe(s) + S(s) → FeS(s)",
            "synthesis",
            "A new compound: not magnetic any more.",
        )
        mix.see("The mixture glows red as it reacts and keeps glowing on its own.")
        mix.special.add("glow")
        mix.warn(
            "warning", "Heating sulfur gives off choking sulfur dioxide: ventilate."
        )


def _flame(mix: Mix) -> None:
    metals: list[str] = []
    for ion in list(mix.ions):
        if mix.ions[ion] <= 0:
            continue
        symbol = re.match(r"^([A-Z][a-z]?)", ion)
        if symbol and symbol.group(1) in FLAME_COLOURS and ion.endswith("+"):
            metals.append(symbol.group(1))
    for portion in mix.portions:
        found = re.match(r"^([A-Z][a-z]?)", portion.chemical.formula)
        if (
            found
            and found.group(1) in FLAME_COLOURS
            and portion.chemical.kind in {"salt", "base"}
        ):
            metals.append(found.group(1))
    metals = list(dict.fromkeys(metals))
    if "B" not in metals and mix.has("boric-acid", "borax"):
        metals.append("B")
    if not metals:
        if mix.has("ethanol", "isopropanol"):
            mix.special.add("flame-blue")
            mix.see("The alcohol burns with a soft blue flame.")
        return
    shown = "Na" if "Na" in metals else metals[0]
    name, colour = FLAME_COLOURS[shown]
    mix.special.add(f"flame:{colour}:{name}")
    mix.see(f"Flame test: a {name} flame ({shown}).")
    if shown == "Na" and len(metals) > 1:
        mix.see(
            "Sodium's strong yellow hides the other colours; a blue cobalt glass would filter it out."
        )


# ------------------------------------------------------------------ results


def _ph(mix: Mix) -> float | None:
    if not mix.wet:
        return None
    litres = mix.litres
    if mix.h > 1e-9:
        return max(-1.0, -math.log10(mix.h / litres))
    if mix.oh > 1e-9:
        return min(14.5, 14 + math.log10(mix.oh / litres))
    for acid in sorted(mix.weak_acids, key=lambda a: a["pka"]):
        if acid["left"] > 1e-9:
            if acid["conj"] > 1e-9:
                return acid["pka"] + math.log10(acid["conj"] / acid["left"])
            return 0.5 * (acid["pka"] - math.log10(acid["left"] / litres))
    carbonate = mix.ions.get("CO32-", 0.0)
    bicarbonate = mix.ions.get("HCO3-", 0.0)
    if carbonate > 1e-9:
        return min(14.0, 14 - 0.5 * (3.67 - math.log10(carbonate / litres)))
    for base in mix.weak_bases:
        if base["left"] > 1e-9:
            if base["conj"] > 1e-9:
                return 14 - (base["pkb"] + math.log10(base["conj"] / base["left"]))
            return 14 - 0.5 * (base["pkb"] - math.log10(base["left"] / litres))
    if bicarbonate > 1e-9:
        return 8.3
    if any(a["conj"] > 0 for a in mix.weak_acids):
        return 8.4
    if any(b["conj"] > 0 for b in mix.weak_bases):
        return 5.4
    if mix.ions.get("Fe3+", 0) > 1e-6 or mix.ions.get("Al3+", 0) > 1e-6:
        return 3.0
    return 7.0


def indicator_colour(indicator: str, ph: float) -> tuple[str, str]:
    """(colour, what it means) for an indicator at a pH."""
    if indicator == "phenolphthalein":
        if ph < 8.2:
            return "#f4f8ff", "colourless (not alkaline)"
        return (
            ("#ff4fb3", "pink (alkaline)")
            if ph < 10
            else ("#d4007a", "magenta (strongly alkaline)")
        )
    if indicator == "bromothymol-blue":
        if ph < 6.0:
            return "#e8d23a", "yellow (acidic)"
        return (
            ("#4caf50", "green (neutral)")
            if ph <= 7.6
            else ("#1e5bd6", "blue (alkaline)")
        )
    if indicator == "red-cabbage":
        steps = (
            (2, "#e0245e", "red"),
            (4, "#e85a9b", "pink"),
            (6, "#9c4dcc", "violet"),
            (7.5, "#7b3fa0", "purple"),
            (8.5, "#3f51b5", "blue"),
            (11, "#26a65b", "green"),
        )
        for top, colour, word in steps:
            if ph < top:
                return colour, word
        return "#e8d23a", "yellow"
    steps = (
        (3, "#e53935", "red: strongly acidic"),
        (5, "#fb8c00", "orange: acidic"),
        (6.5, "#fdd835", "yellow: weakly acidic"),
        (7.5, "#43a047", "green: neutral"),
        (9, "#1e88e5", "blue: alkaline"),
        (11, "#3949ab", "indigo: alkaline"),
    )
    for top, colour, word in steps:
        if ph < top:
            return colour, word
    return "#8e24aa", "purple: strongly alkaline"


def _result(mix: Mix) -> LabData:
    ph = _ph(mix)
    water = mix.water_ml
    total_ml = sum(p.amount for p in mix.portions if p.unit == "mL")
    mass = sum(p.grams for p in mix.portions) or 1.0
    heat_capacity = water * 4.18 + max(0.0, mass - water) * 2.0
    rise = mix.heat_kj * 1000 / heat_capacity if heat_capacity else 0.0
    temperature = ROOM_C + rise
    if mix.heat:
        temperature = max(temperature, 100.0 if mix.wet else 180.0)
    boiling = mix.wet and temperature >= 100
    if boiling:
        temperature = 100.0 if not mix.heat else temperature
        mix.see("It gets hot enough to boil.")
    elif rise > 8:
        mix.see(f"The beaker gets warm (+{rise:.0f} °C).")
    elif rise < -3:
        frost = "; frost forms on the outside" if temperature < 3 else ""
        mix.see(f"The beaker gets cold ({rise:.0f} °C){frost}.")
    if temperature < 0 and mix.wet:
        temperature = max(temperature, -15.0)

    # Colour of the liquid: coloured ions, dyes, and indicators.
    tints = list(mix.tints)
    litres = mix.litres
    for ion, amount in mix.ions.items():
        if ion in ION_COLOURS and amount > 1e-9:
            colour, strength = ION_COLOURS[ion]
            tints.append((colour, min(0.85, strength * amount / litres)))
    indicator_note = ""
    bleached = "bleached" in mix.special
    for portion in mix.portions:
        chemical = portion.chemical
        share = portion.amount / max(total_ml, 1.0)
        if chemical.kind == "indicator" and ph is not None and not bleached:
            colour, meaning = indicator_colour(chemical.id, ph)
            tints.append((colour, 0.8 if colour != "#f4f8ff" else 0.0))
            indicator_note = f"{chemical.name.split(' (')[0]} turns {meaning}."
        elif chemical.roles == ("colour",) and not bleached:
            tints.append((chemical.colour, min(0.9, 0.3 + share * 3)))
        elif (
            not chemical.ions
            and chemical.state in {"liquid", "solution"}
            and chemical.colour not in {"#e8f4ff", "#cfe8ff", "#f5f5f5"}
        ):
            if (
                chemical.kind not in {"indicator", "oil"}
                and "iodine" not in chemical.tags
            ):
                tints.append((chemical.colour, min(0.6, share)))
    if indicator_note:
        mix.see(indicator_note)
    if "starch-iodine" in mix.special:
        tints = [("#141a4d", 2.0)]
    liquid_colour, opacity = blend(tints)
    if mix.colour_steps:
        liquid_colour = mix.colour_steps[-1]
        opacity = 0.12 if liquid_colour == "#e3f2ff" else 0.85
    if "emulsion" in mix.special:
        liquid_colour, opacity = "#f7f3e8", 0.92
    layers: list[LabData] = []
    oily = [p for p in mix.portions if "oil" in p.chemical.tags and p.unit == "mL"]
    if "layers" in mix.special and oily:
        oil_colour, _ = blend([(p.chemical.colour, p.amount) for p in oily])
        oil_ml = sum(p.amount for p in oily)
        layers = [
            {
                "name": "watery layer",
                "colour": liquid_colour,
                "ml": round(total_ml - oil_ml, 1),
                "opacity": opacity,
            },
            {
                "name": "oil layer",
                "colour": oil_colour,
                "ml": round(oil_ml, 1),
                "opacity": 0.75,
            },
        ]
    elif total_ml:
        layers = [
            {
                "name": "mixture",
                "colour": liquid_colour,
                "ml": round(total_ml, 1),
                "opacity": opacity,
            }
        ]

    gases = []
    for entry in mix.gases.values():
        moles = float(str(entry["moles"]))
        millilitres = moles * GAS_ML_PER_MOL
        level = (
            "violent"
            if millilitres > 600 or "violent" in mix.special
            else "lots"
            if millilitres > 120
            else "fizzing"
            if millilitres > 10
            else "a few bubbles"
        )
        gases.append(
            {
                "formula": entry["formula"],
                "name": entry["name"],
                "colour": entry["colour"],
                "ml": round(millilitres, 1),
                "level": level,
            }
        )
    products = []
    for entry in mix.products.values():
        formula = str(entry["formula"])
        moles = float(str(entry["moles"]))
        try:
            grams = moles * molar_mass(formula)
        except FormulaError, KeyError:
            grams = 0.0
        products.append(
            {
                "formula": formula,
                "pretty": pretty(formula)
                if re.fullmatch(r"[A-Za-z0-9()·]+", formula)
                else formula,
                "name": entry["name"],
                "state": entry["state"],
                "moles": round(moles, 5),
                "grams": round(grams, 4),
            }
        )
    dissolved = [
        {"ion": ion, "pretty": ion_pretty(ion), "mol_per_l": round(amount / litres, 4)}
        for ion, amount in sorted(mix.ions.items())
        if amount > 1e-7
    ]
    flame = None
    for mark in mix.special:
        if mark.startswith("flame:"):
            _, colour, name = mark.split(":", 2)
            flame = {"colour": colour, "name": name}
    if "flame-blue" in mix.special:
        flame = {"colour": "#4f7dff", "name": "blue"}
    for portion in mix.portions:
        for code in portion.chemical.hazards:
            level = (
                "danger"
                if code in {"toxic", "corrosive", "reactive-water", "radioactive"}
                else "caution"
            )
            mix.warn(level, f"{portion.chemical.name}: {HAZARDS.get(code, code)}.")
    happened = [r["kind"] for r in mix.reactions]
    summary = _summary(mix, ph, temperature, happened)
    return {
        "vessel": {
            "colour": liquid_colour,
            "opacity": opacity,
            "colour_steps": mix.colour_steps,
            "volume_ml": round(total_ml, 1),
            "water_ml": round(water, 1),
            "temperature_c": round(temperature, 1),
            "ph": round(ph, 2) if ph is not None else None,
            "layers": layers,
            "precipitates": mix.precipitates,
            "solids": [
                {
                    "name": s["name"],
                    "colour": s["colour"],
                    "grams": round(float(str(s["grams"])), 4),
                    "formula": s["formula"],
                }
                for s in mix.solids.values()
            ],
            "gases": gases,
            "foam": round(mix.foam, 2),
            "flame": flame,
            "boiling": boiling,
            "effects": sorted(
                mark for mark in mix.special if not mark.startswith("flame:")
            ),
        },
        "ingredients": [
            {
                "id": p.chemical.id,
                "name": p.chemical.name,
                "formula": p.chemical.formula,
                "amount": p.amount,
                "unit": p.unit,
                "colour": p.chemical.colour,
            }
            for p in mix.portions
        ],
        "reactions": mix.reactions,
        "observations": mix.observations,
        "hazards": mix.hazards,
        "products": products,
        "dissolved": dissolved,
        "summary": summary,
        "unknown": mix.unknown,
        "source": "rules",
    }


def _summary(
    mix: Mix, ph: float | None, temperature: float, happened: list[str]
) -> str:
    parts: list[str] = []
    if not mix.portions:
        return "Nothing the Lab knows is in the beaker yet."
    if happened:
        kinds = ", ".join(dict.fromkeys(happened))
        parts.append(f"Reactions: {kinds}.")
    else:
        parts.append("No chemical reaction: the substances just mix.")
    if mix.precipitates:
        parts.append(
            "Solid formed: " + ", ".join(str(p["name"]) for p in mix.precipitates) + "."
        )
    if mix.gases:
        parts.append(
            "Gas given off: "
            + ", ".join(str(g["name"]) for g in mix.gases.values())
            + "."
        )
    if ph is not None:
        word = (
            "strongly acidic"
            if ph < 3
            else "acidic"
            if ph < 6.5
            else "neutral"
            if ph <= 7.5
            else "alkaline"
            if ph < 11
            else "strongly alkaline"
        )
        parts.append(f"pH about {ph:.1f} ({word}).")
    if abs(temperature - ROOM_C) >= 2:
        parts.append(f"Temperature {temperature:.0f} °C.")
    if mix.unknown:
        parts.append("Not on the shelf: " + ", ".join(mix.unknown) + ".")
    return " ".join(parts)
