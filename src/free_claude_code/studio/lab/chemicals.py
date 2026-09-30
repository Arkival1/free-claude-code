"""The Lab's chemical shelf: what each chemical is and how it behaves.

Each entry carries what the simulator needs: the ions it gives in water,
how strong an acid or base it is, its colour, what happens when it dissolves,
and its hazards. Anything not here can be looked up on PubChem.
"""

from dataclasses import dataclass, field
from typing import Any

from . import LabData
from .formula import FormulaError, molar_mass

HAZARDS = {
    "corrosive": "Corrosive: burns skin and eyes",
    "toxic": "Toxic if swallowed, inhaled, or on skin",
    "harmful": "Harmful: irritates and can make you ill",
    "irritant": "Irritates skin and eyes",
    "flammable": "Flammable: keep away from flames",
    "oxidizer": "Oxidiser: makes fires burn fiercely",
    "environment": "Harmful to water life",
    "reactive-water": "Reacts violently with water",
    "radioactive": "Radioactive",
}


@dataclass(frozen=True, slots=True)
class Chemical:
    id: str
    name: str
    formula: str
    kind: str
    """acid, base, salt, metal, solvent, oxidizer, surfactant, oil, sugar,
    polymer, indicator, household, cosmetic, gas, element, mixture."""
    state: str
    """solid, liquid, gas, or solution (a stock solution in water)."""
    colour: str = "#e8f4ff"
    concentration: float = 0.0
    """Moles per litre, for stock solutions."""
    ions: tuple[tuple[str, float], ...] = ()
    """Ions released per formula unit in water."""
    acid: tuple[str, float, int] | None = None
    """(strong|weak, pKa, protons)."""
    base: tuple[str, float, int] | None = None
    """(strong|weak, pKb, hydroxides)."""
    density: float = 1.0
    hazards: tuple[str, ...] = ()
    roles: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    dissolve_heat: float = 0.0
    """kJ given out per mole dissolving (negative feels cold)."""
    tags: frozenset[str] = field(default_factory=frozenset)
    """Behaviours: carbonate, active-metal, very-active-metal, fuel,
    peroxide-catalyst, peroxide, hypochlorite, ammonia, oil, surfactant,
    starch, iodine, reducer, permanganate, hydrated, sugar, soluble-oil."""
    note: str = ""

    @property
    def molar_mass(self) -> float:
        if not self.formula:
            return 0.0
        try:
            return molar_mass(self.formula)
        except FormulaError:
            return 0.0

    def view(self) -> LabData:
        return {
            "id": self.id,
            "name": self.name,
            "formula": self.formula,
            "kind": self.kind,
            "state": self.state,
            "colour": self.colour,
            "concentration": self.concentration,
            "molar_mass": self.molar_mass,
            "density": self.density,
            "hazards": [
                {"code": code, "text": HAZARDS.get(code, code)} for code in self.hazards
            ],
            "roles": list(self.roles),
            "aliases": list(self.aliases),
            "tags": sorted(self.tags),
            "note": self.note,
            "source": "shelf",
        }


def _c(
    id: str,
    name: str,
    formula: str,
    kind: str,
    state: str,
    colour: str = "#e8f4ff",
    *,
    tags: str = "",
    **fields: Any,
) -> Chemical:
    return Chemical(
        id=id,
        name=name,
        formula=formula,
        kind=kind,
        state=state,
        colour=colour,
        tags=frozenset(tags.split()),
        **fields,
    )


CLEAR = "#e8f4ff"
WHITE = "#f5f5f5"

CHEMICALS: tuple[Chemical, ...] = (
    # ------------------------------------------------------------ water & solvents
    _c(
        "water",
        "Water",
        "H2O",
        "solvent",
        "liquid",
        "#cfe8ff",
        aliases=("h2o", "distilled water"),
        roles=("solvent",),
    ),
    _c(
        "ethanol",
        "Ethanol",
        "C2H5OH",
        "solvent",
        "liquid",
        CLEAR,
        density=0.789,
        hazards=("flammable",),
        tags="fuel",
        aliases=("alcohol", "ethyl alcohol"),
        roles=("solvent", "antiseptic"),
    ),
    _c(
        "isopropanol",
        "Isopropyl alcohol",
        "C3H7OH",
        "solvent",
        "liquid",
        CLEAR,
        density=0.786,
        hazards=("flammable", "irritant"),
        tags="fuel",
        aliases=("rubbing alcohol", "ipa", "isopropanol"),
        roles=("solvent", "antiseptic"),
    ),
    _c(
        "acetone",
        "Acetone",
        "C3H6O",
        "solvent",
        "liquid",
        CLEAR,
        density=0.784,
        hazards=("flammable", "irritant"),
        tags="fuel",
        aliases=("nail polish remover", "propanone"),
    ),
    _c(
        "glycerol",
        "Glycerin",
        "C3H8O3",
        "cosmetic",
        "liquid",
        CLEAR,
        density=1.26,
        aliases=("glycerol", "glycerine"),
        roles=("humectant",),
    ),
    _c(
        "propylene-glycol",
        "Propylene glycol",
        "C3H8O2",
        "cosmetic",
        "liquid",
        CLEAR,
        density=1.04,
        roles=("humectant", "solvent"),
    ),
    # ------------------------------------------------------------------- acids
    _c(
        "hydrochloric-acid",
        "Hydrochloric acid (1 M)",
        "HCl",
        "acid",
        "solution",
        CLEAR,
        concentration=1.0,
        ions=(("H+", 1), ("Cl-", 1)),
        acid=("strong", -6.3, 1),
        hazards=("corrosive",),
        aliases=("hcl", "muriatic acid"),
    ),
    _c(
        "sulfuric-acid",
        "Sulfuric acid (1 M)",
        "H2SO4",
        "acid",
        "solution",
        CLEAR,
        concentration=1.0,
        ions=(("H+", 2), ("SO42-", 1)),
        acid=("strong", -3.0, 2),
        hazards=("corrosive",),
        aliases=("h2so4", "battery acid", "sulphuric acid"),
    ),
    _c(
        "nitric-acid",
        "Nitric acid (1 M)",
        "HNO3",
        "acid",
        "solution",
        CLEAR,
        concentration=1.0,
        ions=(("H+", 1), ("NO3-", 1)),
        acid=("strong", -1.4, 1),
        hazards=("corrosive", "oxidizer"),
        aliases=("hno3",),
    ),
    _c(
        "acetic-acid",
        "Vinegar (acetic acid, 0.8 M)",
        "CH3COOH",
        "acid",
        "solution",
        CLEAR,
        concentration=0.83,
        ions=(("H+", 1), ("CH3COO-", 1)),
        acid=("weak", 4.76, 1),
        aliases=("vinegar", "acetic acid", "ethanoic acid"),
        roles=("ph-adjuster", "cleaner"),
    ),
    _c(
        "citric-acid",
        "Citric acid",
        "C6H8O7",
        "acid",
        "solid",
        WHITE,
        ions=(("H+", 3), ("C6H5O73-", 1)),
        acid=("weak", 3.13, 3),
        dissolve_heat=-22.0,
        aliases=("citric",),
        roles=("ph-adjuster", "chelator", "fizz-acid"),
    ),
    _c(
        "ascorbic-acid",
        "Vitamin C (ascorbic acid)",
        "C6H8O6",
        "acid",
        "solid",
        WHITE,
        ions=(("H+", 1),),
        acid=("weak", 4.10, 1),
        tags="reducer",
        aliases=("vitamin c", "ascorbic"),
        roles=("antioxidant",),
    ),
    _c(
        "lactic-acid",
        "Lactic acid",
        "C3H6O3",
        "acid",
        "liquid",
        CLEAR,
        ions=(("H+", 1),),
        acid=("weak", 3.86, 1),
        density=1.21,
        roles=("ph-adjuster", "exfoliant"),
    ),
    _c(
        "phosphoric-acid",
        "Phosphoric acid (1 M)",
        "H3PO4",
        "acid",
        "solution",
        CLEAR,
        concentration=1.0,
        ions=(("H+", 1), ("PO43-", 0.33)),
        acid=("weak", 2.15, 1),
        hazards=("corrosive",),
    ),
    _c(
        "oxalic-acid",
        "Oxalic acid",
        "C2H2O4",
        "acid",
        "solid",
        WHITE,
        ions=(("H+", 2),),
        acid=("weak", 1.25, 2),
        hazards=("harmful",),
        tags="reducer",
    ),
    _c(
        "boric-acid",
        "Boric acid",
        "H3BO3",
        "acid",
        "solid",
        WHITE,
        acid=("weak", 9.24, 1),
        hazards=("harmful",),
    ),
    _c(
        "salicylic-acid",
        "Salicylic acid",
        "C7H6O3",
        "acid",
        "solid",
        WHITE,
        acid=("weak", 2.97, 1),
        roles=("exfoliant",),
    ),
    _c(
        "stearic-acid",
        "Stearic acid",
        "C18H36O2",
        "cosmetic",
        "solid",
        WHITE,
        roles=("thickener", "emulsifier"),
    ),
    # ------------------------------------------------------------------- bases
    _c(
        "sodium-hydroxide",
        "Sodium hydroxide (1 M)",
        "NaOH",
        "base",
        "solution",
        CLEAR,
        concentration=1.0,
        ions=(("Na+", 1), ("OH-", 1)),
        base=("strong", -0.2, 1),
        hazards=("corrosive",),
        aliases=("lye", "caustic soda", "naoh"),
    ),
    _c(
        "sodium-hydroxide-solid",
        "Sodium hydroxide pellets",
        "NaOH",
        "base",
        "solid",
        WHITE,
        ions=(("Na+", 1), ("OH-", 1)),
        base=("strong", -0.2, 1),
        hazards=("corrosive",),
        dissolve_heat=44.5,
        aliases=("lye pellets",),
    ),
    _c(
        "potassium-hydroxide",
        "Potassium hydroxide (1 M)",
        "KOH",
        "base",
        "solution",
        CLEAR,
        concentration=1.0,
        ions=(("K+", 1), ("OH-", 1)),
        base=("strong", -0.5, 1),
        hazards=("corrosive",),
        aliases=("potash lye", "koh"),
    ),
    _c(
        "calcium-hydroxide",
        "Limewater (calcium hydroxide)",
        "Ca(OH)2",
        "base",
        "solution",
        CLEAR,
        concentration=0.02,
        ions=(("Ca2+", 1), ("OH-", 2)),
        base=("strong", 1.37, 2),
        hazards=("irritant",),
        aliases=("limewater", "slaked lime"),
    ),
    _c(
        "ammonia",
        "Household ammonia (1 M)",
        "NH3",
        "base",
        "solution",
        CLEAR,
        concentration=1.0,
        ions=(("NH4+", 1), ("OH-", 1)),
        base=("weak", 4.75, 1),
        hazards=("irritant", "harmful"),
        tags="ammonia",
        aliases=("ammonia", "ammonium hydroxide", "nh3"),
    ),
    _c(
        "sodium-bicarbonate",
        "Baking soda (sodium bicarbonate)",
        "NaHCO3",
        "base",
        "solid",
        WHITE,
        ions=(("Na+", 1), ("HCO3-", 1)),
        base=("weak", 7.65, 1),
        tags="carbonate",
        dissolve_heat=-18.7,
        aliases=("baking soda", "bicarbonate of soda", "bicarb"),
        roles=("fizz-base", "deodoriser"),
    ),
    _c(
        "sodium-carbonate",
        "Washing soda (sodium carbonate)",
        "Na2CO3",
        "base",
        "solid",
        WHITE,
        ions=(("Na+", 2), ("CO32-", 1)),
        base=("weak", 3.67, 1),
        tags="carbonate",
        hazards=("irritant",),
        dissolve_heat=26.7,
        aliases=("washing soda", "soda ash"),
    ),
    _c(
        "calcium-carbonate",
        "Chalk (calcium carbonate)",
        "CaCO3",
        "salt",
        "solid",
        WHITE,
        tags="carbonate insoluble",
        aliases=("chalk", "limestone", "marble"),
        roles=("abrasive", "filler"),
    ),
    _c(
        "magnesium-hydroxide",
        "Milk of magnesia",
        "Mg(OH)2",
        "base",
        "solid",
        WHITE,
        base=("weak", 3.0, 2),
        tags="insoluble",
        aliases=("milk of magnesia",),
    ),
    # -------------------------------------------------------------------- salts
    _c(
        "sodium-chloride",
        "Table salt (sodium chloride)",
        "NaCl",
        "salt",
        "solid",
        WHITE,
        ions=(("Na+", 1), ("Cl-", 1)),
        dissolve_heat=-3.9,
        aliases=("salt", "table salt", "nacl"),
        roles=("thickener", "flavour"),
    ),
    _c(
        "potassium-chloride",
        "Potassium chloride",
        "KCl",
        "salt",
        "solid",
        WHITE,
        ions=(("K+", 1), ("Cl-", 1)),
        dissolve_heat=-17.2,
    ),
    _c(
        "calcium-chloride",
        "Calcium chloride",
        "CaCl2",
        "salt",
        "solid",
        WHITE,
        ions=(("Ca2+", 1), ("Cl-", 2)),
        dissolve_heat=82.8,
        hazards=("irritant",),
        aliases=("road salt",),
    ),
    _c(
        "magnesium-sulfate",
        "Epsom salt (magnesium sulfate)",
        "MgSO4",
        "salt",
        "solid",
        WHITE,
        ions=(("Mg2+", 1), ("SO42-", 1)),
        dissolve_heat=13.3,
        aliases=("epsom salt",),
    ),
    _c(
        "sodium-sulfate",
        "Sodium sulfate",
        "Na2SO4",
        "salt",
        "solid",
        WHITE,
        ions=(("Na+", 2), ("SO42-", 1)),
    ),
    _c(
        "ammonium-nitrate",
        "Ammonium nitrate",
        "NH4NO3",
        "salt",
        "solid",
        WHITE,
        ions=(("NH4+", 1), ("NO3-", 1)),
        dissolve_heat=-25.7,
        hazards=("oxidizer",),
        note="Soaks up heat as it dissolves: the chemical in instant cold packs.",
    ),
    _c(
        "ammonium-chloride",
        "Ammonium chloride",
        "NH4Cl",
        "salt",
        "solid",
        WHITE,
        ions=(("NH4+", 1), ("Cl-", 1)),
        dissolve_heat=-14.8,
        hazards=("harmful",),
    ),
    _c(
        "potassium-iodide",
        "Potassium iodide (0.1 M)",
        "KI",
        "salt",
        "solution",
        CLEAR,
        concentration=0.1,
        ions=(("K+", 1), ("I-", 1)),
        tags="peroxide-catalyst",
        aliases=("ki",),
    ),
    _c(
        "potassium-bromide",
        "Potassium bromide (0.1 M)",
        "KBr",
        "salt",
        "solution",
        CLEAR,
        concentration=0.1,
        ions=(("K+", 1), ("Br-", 1)),
    ),
    _c(
        "lead-nitrate",
        "Lead(II) nitrate (0.1 M)",
        "Pb(NO3)2",
        "salt",
        "solution",
        CLEAR,
        concentration=0.1,
        ions=(("Pb2+", 1), ("NO3-", 2)),
        hazards=("toxic", "environment", "oxidizer"),
    ),
    _c(
        "silver-nitrate",
        "Silver nitrate (0.1 M)",
        "AgNO3",
        "salt",
        "solution",
        CLEAR,
        concentration=0.1,
        ions=(("Ag+", 1), ("NO3-", 1)),
        hazards=("corrosive", "environment"),
        note="Stains skin black in sunlight.",
    ),
    _c(
        "barium-chloride",
        "Barium chloride (0.1 M)",
        "BaCl2",
        "salt",
        "solution",
        CLEAR,
        concentration=0.1,
        ions=(("Ba2+", 1), ("Cl-", 2)),
        hazards=("toxic",),
    ),
    _c(
        "copper-sulfate",
        "Copper(II) sulfate (0.5 M)",
        "CuSO4",
        "salt",
        "solution",
        "#3a8dff",
        concentration=0.5,
        ions=(("Cu2+", 1), ("SO42-", 1)),
        hazards=("harmful", "environment"),
        aliases=("blue vitriol", "copper sulfate solution"),
    ),
    _c(
        "copper-sulfate-crystals",
        "Copper(II) sulfate crystals",
        "CuSO4·5H2O",
        "salt",
        "solid",
        "#1e6fff",
        ions=(("Cu2+", 1), ("SO42-", 1)),
        hazards=("harmful", "environment"),
        tags="hydrated",
    ),
    _c(
        "iron-iii-chloride",
        "Iron(III) chloride (0.1 M)",
        "FeCl3",
        "salt",
        "solution",
        "#d9a03a",
        concentration=0.1,
        ions=(("Fe3+", 1), ("Cl-", 3)),
        hazards=("corrosive",),
    ),
    _c(
        "iron-ii-sulfate",
        "Iron(II) sulfate (0.1 M)",
        "FeSO4",
        "salt",
        "solution",
        "#b8d8a8",
        concentration=0.1,
        ions=(("Fe2+", 1), ("SO42-", 1)),
        tags="reducer",
        hazards=("harmful",),
    ),
    _c(
        "nickel-chloride",
        "Nickel(II) chloride (0.1 M)",
        "NiCl2",
        "salt",
        "solution",
        "#57b86a",
        concentration=0.1,
        ions=(("Ni2+", 1), ("Cl-", 2)),
        hazards=("toxic",),
    ),
    _c(
        "cobalt-chloride",
        "Cobalt(II) chloride (0.1 M)",
        "CoCl2",
        "salt",
        "solution",
        "#e38aa8",
        concentration=0.1,
        ions=(("Co2+", 1), ("Cl-", 2)),
        hazards=("toxic",),
    ),
    _c(
        "zinc-sulfate",
        "Zinc sulfate (0.1 M)",
        "ZnSO4",
        "salt",
        "solution",
        CLEAR,
        concentration=0.1,
        ions=(("Zn2+", 1), ("SO42-", 1)),
        hazards=("harmful",),
    ),
    _c(
        "aluminium-sulfate",
        "Aluminium sulfate (0.1 M)",
        "Al2(SO4)3",
        "salt",
        "solution",
        CLEAR,
        concentration=0.1,
        ions=(("Al3+", 2), ("SO42-", 3)),
        aliases=("alum",),
    ),
    _c(
        "magnesium-chloride",
        "Magnesium chloride (0.1 M)",
        "MgCl2",
        "salt",
        "solution",
        CLEAR,
        concentration=0.1,
        ions=(("Mg2+", 1), ("Cl-", 2)),
    ),
    _c(
        "lithium-chloride",
        "Lithium chloride",
        "LiCl",
        "salt",
        "solid",
        WHITE,
        ions=(("Li+", 1), ("Cl-", 1)),
        dissolve_heat=37.0,
        hazards=("harmful",),
    ),
    _c(
        "strontium-chloride",
        "Strontium chloride",
        "SrCl2",
        "salt",
        "solid",
        WHITE,
        ions=(("Sr2+", 1), ("Cl-", 2)),
        hazards=("irritant",),
    ),
    _c(
        "sodium-phosphate",
        "Trisodium phosphate (0.1 M)",
        "Na3PO4",
        "salt",
        "solution",
        CLEAR,
        concentration=0.1,
        ions=(("Na+", 3), ("PO43-", 1)),
        base=("weak", 1.65, 1),
        hazards=("irritant",),
    ),
    _c(
        "potassium-chromate",
        "Potassium chromate (0.1 M)",
        "K2CrO4",
        "salt",
        "solution",
        "#f5d000",
        concentration=0.1,
        ions=(("K+", 2), ("CrO42-", 1)),
        hazards=("toxic", "environment"),
    ),
    _c(
        "sodium-sulfide",
        "Sodium sulfide (0.1 M)",
        "Na2S",
        "salt",
        "solution",
        "#fff8d0",
        concentration=0.1,
        ions=(("Na+", 2), ("S2-", 1)),
        hazards=("toxic", "corrosive"),
    ),
    _c(
        "sodium-fluoride",
        "Sodium fluoride",
        "NaF",
        "salt",
        "solid",
        WHITE,
        ions=(("Na+", 1), ("F-", 1)),
        hazards=("toxic",),
        roles=("anti-cavity",),
    ),
    _c(
        "sodium-thiosulfate",
        "Sodium thiosulfate (0.1 M)",
        "Na2S2O3",
        "salt",
        "solution",
        CLEAR,
        concentration=0.1,
        ions=(("Na+", 2),),
        tags="reducer",
    ),
    _c(
        "borax",
        "Borax (sodium tetraborate)",
        "Na2B4O7·10H2O",
        "salt",
        "solid",
        WHITE,
        ions=(("Na+", 2),),
        base=("weak", 8.0, 1),
        hazards=("harmful",),
        aliases=("borax",),
        roles=("crosslinker", "cleaner"),
    ),
    _c(
        "potassium-nitrate",
        "Potassium nitrate",
        "KNO3",
        "salt",
        "solid",
        WHITE,
        ions=(("K+", 1), ("NO3-", 1)),
        hazards=("oxidizer",),
        dissolve_heat=-34.9,
        aliases=("saltpetre",),
    ),
    _c(
        "sodium-citrate",
        "Sodium citrate",
        "Na3C6H5O7",
        "salt",
        "solid",
        WHITE,
        ions=(("Na+", 3), ("C6H5O73-", 1)),
        roles=("buffer", "chelator"),
    ),
    _c(
        "potassium-citrate",
        "Potassium citrate",
        "K3C6H5O7",
        "salt",
        "solid",
        WHITE,
        ions=(("K+", 3), ("C6H5O73-", 1)),
        roles=("electrolyte",),
    ),
    _c(
        "sodium-benzoate",
        "Sodium benzoate",
        "C7H5NaO2",
        "cosmetic",
        "solid",
        WHITE,
        ions=(("Na+", 1),),
        roles=("preservative",),
    ),
    _c(
        "disodium-edta",
        "Disodium EDTA",
        "C10H14N2Na2O8",
        "cosmetic",
        "solid",
        WHITE,
        ions=(("Na+", 2),),
        roles=("chelator",),
    ),
    # --------------------------------------------------------- oxidisers & more
    _c(
        "hydrogen-peroxide",
        "Hydrogen peroxide (3%)",
        "H2O2",
        "oxidizer",
        "solution",
        CLEAR,
        concentration=0.88,
        tags="peroxide",
        hazards=("irritant",),
        aliases=("peroxide", "h2o2"),
        roles=("antiseptic", "bleach"),
    ),
    _c(
        "hydrogen-peroxide-strong",
        "Hydrogen peroxide (30%)",
        "H2O2",
        "oxidizer",
        "solution",
        CLEAR,
        concentration=9.8,
        tags="peroxide",
        hazards=("corrosive", "oxidizer"),
    ),
    _c(
        "bleach",
        "Bleach (sodium hypochlorite, 5%)",
        "NaClO",
        "household",
        "solution",
        "#f4ffe0",
        concentration=0.7,
        ions=(("Na+", 1), ("OCl-", 1)),
        base=("weak", 6.5, 1),
        tags="hypochlorite",
        hazards=("corrosive", "environment"),
        aliases=("bleach", "sodium hypochlorite", "chlorine bleach"),
    ),
    _c(
        "potassium-permanganate",
        "Potassium permanganate (0.02 M)",
        "KMnO4",
        "oxidizer",
        "solution",
        "#8e24aa",
        concentration=0.02,
        ions=(("K+", 1), ("MnO4-", 1)),
        tags="permanganate",
        hazards=("oxidizer", "harmful", "environment"),
    ),
    _c(
        "manganese-dioxide",
        "Manganese dioxide",
        "MnO2",
        "oxidizer",
        "solid",
        "#3b2f2f",
        tags="peroxide-catalyst insoluble",
        hazards=("harmful",),
    ),
    _c(
        "iodine",
        "Iodine tincture",
        "I2",
        "element",
        "solution",
        "#8a4b0f",
        concentration=0.08,
        tags="iodine",
        hazards=("harmful",),
        aliases=("iodine", "tincture of iodine"),
    ),
    _c(
        "yeast",
        "Baker's yeast (catalase)",
        "",
        "mixture",
        "solid",
        "#d7b98e",
        tags="peroxide-catalyst",
        aliases=("yeast",),
    ),
    # -------------------------------------------------------------------- metals
    _c(
        "magnesium",
        "Magnesium ribbon",
        "Mg",
        "metal",
        "solid",
        "#c9ccd1",
        tags="active-metal fuel",
        hazards=("flammable",),
        aliases=("mg",),
    ),
    _c(
        "zinc",
        "Zinc granules",
        "Zn",
        "metal",
        "solid",
        "#a9b0b8",
        tags="active-metal",
        aliases=("zn",),
    ),
    _c(
        "iron",
        "Iron filings",
        "Fe",
        "metal",
        "solid",
        "#5d5d5d",
        tags="active-metal",
        aliases=("fe", "iron powder"),
    ),
    _c(
        "aluminium",
        "Aluminium foil",
        "Al",
        "metal",
        "solid",
        "#d6dbe0",
        tags="active-metal",
        aliases=("aluminum", "al", "tin foil"),
    ),
    _c("copper", "Copper turnings", "Cu", "metal", "solid", "#c46a3a", aliases=("cu",)),
    _c("tin", "Tin", "Sn", "metal", "solid", "#bfc5c9", tags="active-metal"),
    _c("silver", "Silver", "Ag", "metal", "solid", "#e3e6ea"),
    _c("gold", "Gold", "Au", "metal", "solid", "#f5c542"),
    _c(
        "sodium-metal",
        "Sodium metal",
        "Na",
        "metal",
        "solid",
        "#d9dde2",
        tags="very-active-metal",
        hazards=("reactive-water", "flammable", "corrosive"),
    ),
    _c(
        "potassium-metal",
        "Potassium metal",
        "K",
        "metal",
        "solid",
        "#d0d4da",
        tags="very-active-metal",
        hazards=("reactive-water", "flammable", "corrosive"),
    ),
    _c(
        "lithium-metal",
        "Lithium metal",
        "Li",
        "metal",
        "solid",
        "#c8ccd2",
        tags="very-active-metal",
        hazards=("reactive-water", "flammable"),
    ),
    _c(
        "calcium-metal",
        "Calcium metal",
        "Ca",
        "metal",
        "solid",
        "#d9d9d0",
        tags="very-active-metal",
        hazards=("reactive-water",),
    ),
    _c(
        "sulfur",
        "Sulfur powder",
        "S",
        "element",
        "solid",
        "#f2e03a",
        tags="fuel insoluble",
        hazards=("flammable",),
    ),
    _c(
        "carbon",
        "Activated charcoal",
        "C",
        "element",
        "solid",
        "#1f1f1f",
        tags="fuel insoluble",
        aliases=("charcoal", "graphite"),
    ),
    # -------------------------------------------------------- sugars & food
    _c(
        "sucrose",
        "Sugar (sucrose)",
        "C12H22O11",
        "sugar",
        "solid",
        WHITE,
        tags="fuel sugar",
        aliases=("sugar", "table sugar"),
    ),
    _c(
        "glucose",
        "Glucose",
        "C6H12O6",
        "sugar",
        "solid",
        WHITE,
        tags="fuel sugar reducer",
        aliases=("dextrose",),
    ),
    _c(
        "starch",
        "Corn starch",
        "(C6H10O5)n",
        "polymer",
        "solid",
        WHITE,
        tags="starch fuel",
        aliases=("cornstarch", "cornflour", "starch"),
    ),
    _c(
        "red-cabbage",
        "Red cabbage juice (indicator)",
        "",
        "indicator",
        "solution",
        "#7b3fa0",
        aliases=("cabbage juice",),
    ),
    _c(
        "milk",
        "Milk",
        "",
        "mixture",
        "liquid",
        "#fbfbf5",
        tags="protein",
        aliases=("milk",),
    ),
    _c(
        "food-colouring-red",
        "Food colouring (red)",
        "",
        "mixture",
        "liquid",
        "#e53935",
        aliases=("red dye",),
        roles=("colour",),
    ),
    _c(
        "food-colouring-blue",
        "Food colouring (blue)",
        "",
        "mixture",
        "liquid",
        "#1e88e5",
        aliases=("blue dye",),
        roles=("colour",),
    ),
    _c(
        "food-colouring-yellow",
        "Food colouring (yellow)",
        "",
        "mixture",
        "liquid",
        "#fdd835",
        aliases=("yellow dye",),
        roles=("colour",),
    ),
    # ---------------------------------------------------------------- indicators
    _c(
        "phenolphthalein",
        "Phenolphthalein (indicator)",
        "C20H14O4",
        "indicator",
        "solution",
        CLEAR,
        hazards=("harmful",),
    ),
    _c(
        "universal-indicator",
        "Universal indicator",
        "",
        "indicator",
        "solution",
        "#4caf50",
    ),
    _c(
        "bromothymol-blue",
        "Bromothymol blue (indicator)",
        "C27H28Br2O5S",
        "indicator",
        "solution",
        "#2e7d32",
    ),
    # ------------------------------------------------------------- oils & waxes
    _c(
        "olive-oil",
        "Olive oil",
        "",
        "oil",
        "liquid",
        "#c8b53a",
        density=0.91,
        tags="oil fuel",
        roles=("emollient", "soap-oil"),
    ),
    _c(
        "coconut-oil",
        "Coconut oil",
        "",
        "oil",
        "liquid",
        "#f7f3e3",
        density=0.92,
        tags="oil fuel",
        roles=("emollient", "soap-oil"),
    ),
    _c(
        "sunflower-oil",
        "Sunflower oil",
        "",
        "oil",
        "liquid",
        "#e8c93a",
        density=0.92,
        tags="oil fuel",
        roles=("emollient",),
    ),
    _c(
        "castor-oil",
        "Castor oil",
        "",
        "oil",
        "liquid",
        "#e9dfa8",
        density=0.96,
        tags="oil fuel",
        roles=("emollient", "soap-oil"),
    ),
    _c(
        "mineral-oil",
        "Mineral oil",
        "",
        "oil",
        "liquid",
        CLEAR,
        density=0.85,
        tags="oil fuel",
        roles=("emollient",),
    ),
    _c(
        "shea-butter",
        "Shea butter",
        "",
        "oil",
        "solid",
        "#f3ead3",
        tags="oil fuel",
        roles=("emollient",),
    ),
    _c(
        "beeswax",
        "Beeswax",
        "",
        "oil",
        "solid",
        "#e8b64c",
        tags="oil fuel",
        roles=("thickener", "structure"),
    ),
    _c(
        "paraffin-wax",
        "Paraffin wax",
        "",
        "oil",
        "solid",
        "#f7f7f2",
        tags="oil fuel",
        roles=("structure",),
    ),
    _c(
        "soy-wax",
        "Soy wax",
        "",
        "oil",
        "solid",
        "#f5f1e1",
        tags="oil fuel",
        roles=("structure",),
    ),
    _c(
        "vitamin-e",
        "Vitamin E (tocopherol)",
        "C29H50O2",
        "cosmetic",
        "liquid",
        "#d8b33a",
        tags="oil",
        roles=("antioxidant",),
    ),
    _c(
        "fragrance",
        "Fragrance oil",
        "",
        "cosmetic",
        "liquid",
        "#ffe9c4",
        tags="oil",
        roles=("fragrance",),
        aliases=("perfume oil",),
    ),
    _c(
        "peppermint-oil",
        "Peppermint oil",
        "",
        "cosmetic",
        "liquid",
        "#e9ffe9",
        tags="oil",
        roles=("flavour", "fragrance"),
    ),
    # -------------------------------------------------------------- surfactants
    _c(
        "sles",
        "Sodium laureth sulfate",
        "C16H33NaO6S",
        "surfactant",
        "solution",
        "#fffbe8",
        ions=(("Na+", 1),),
        tags="surfactant",
        hazards=("irritant",),
        aliases=("sles", "sodium lauryl ether sulfate"),
        roles=("cleansing surfactant",),
    ),
    _c(
        "sls",
        "Sodium lauryl sulfate",
        "C12H25NaO4S",
        "surfactant",
        "solid",
        WHITE,
        ions=(("Na+", 1),),
        tags="surfactant",
        hazards=("irritant",),
        aliases=("sls", "sodium dodecyl sulfate"),
        roles=("cleansing surfactant", "foaming agent"),
    ),
    _c(
        "capb",
        "Cocamidopropyl betaine",
        "C19H38N2O3",
        "surfactant",
        "solution",
        "#fff6d6",
        tags="surfactant",
        aliases=("betaine", "capb"),
        roles=("mild co-surfactant", "foam booster"),
    ),
    _c(
        "decyl-glucoside",
        "Decyl glucoside",
        "C16H32O6",
        "surfactant",
        "solution",
        "#fff4d0",
        tags="surfactant",
        roles=("gentle surfactant",),
    ),
    _c(
        "dish-soap",
        "Dish soap",
        "",
        "household",
        "liquid",
        "#9ccc65",
        tags="surfactant",
        aliases=("washing up liquid", "detergent", "soap"),
    ),
    _c(
        "sodium-stearate",
        "Soap (sodium stearate)",
        "C18H35NaO2",
        "surfactant",
        "solid",
        WHITE,
        ions=(("Na+", 1),),
        base=("weak", 9.0, 1),
        tags="surfactant",
        aliases=("bar soap",),
    ),
    _c(
        "polysorbate-20",
        "Polysorbate 20",
        "",
        "cosmetic",
        "liquid",
        "#fff1c1",
        tags="surfactant soluble-oil",
        roles=("solubiliser",),
    ),
    _c(
        "emulsifying-wax",
        "Emulsifying wax (cetearyl alcohol, ceteareth-20)",
        "",
        "cosmetic",
        "solid",
        WHITE,
        tags="surfactant",
        roles=("emulsifier",),
    ),
    _c(
        "cetearyl-alcohol",
        "Cetearyl alcohol",
        "C16H34O",
        "cosmetic",
        "solid",
        WHITE,
        roles=("thickener", "emollient"),
    ),
    # ------------------------------------------------------------- cosmetics
    _c(
        "panthenol",
        "Panthenol (pro-vitamin B5)",
        "C9H19NO4",
        "cosmetic",
        "liquid",
        CLEAR,
        density=1.2,
        roles=("conditioning", "moisturiser"),
    ),
    _c(
        "polyquaternium-10",
        "Polyquaternium-10",
        "",
        "cosmetic",
        "solid",
        WHITE,
        roles=("conditioning polymer",),
    ),
    _c(
        "xanthan-gum",
        "Xanthan gum",
        "",
        "polymer",
        "solid",
        "#f2ecd9",
        roles=("thickener",),
    ),
    _c(
        "phenoxyethanol",
        "Phenoxyethanol",
        "C8H10O2",
        "cosmetic",
        "liquid",
        CLEAR,
        density=1.1,
        hazards=("harmful",),
        roles=("preservative",),
    ),
    _c(
        "sorbitol",
        "Sorbitol",
        "C6H14O6",
        "cosmetic",
        "solution",
        CLEAR,
        roles=("humectant", "sweetener"),
    ),
    _c(
        "sodium-saccharin",
        "Sodium saccharin",
        "C7H4NNaO3S",
        "cosmetic",
        "solid",
        WHITE,
        roles=("sweetener",),
    ),
    _c(
        "titanium-dioxide",
        "Titanium dioxide",
        "TiO2",
        "cosmetic",
        "solid",
        "#ffffff",
        tags="insoluble",
        roles=("white pigment", "UV filter"),
    ),
    _c(
        "zinc-oxide",
        "Zinc oxide",
        "ZnO",
        "cosmetic",
        "solid",
        "#fafafa",
        tags="insoluble",
        roles=("UV filter", "soothing"),
    ),
    _c(
        "aloe-vera",
        "Aloe vera gel",
        "",
        "cosmetic",
        "liquid",
        "#e6f5d0",
        roles=("soothing",),
    ),
    _c(
        "hyaluronic-acid",
        "Sodium hyaluronate",
        "",
        "cosmetic",
        "solid",
        WHITE,
        roles=("humectant",),
    ),
    _c(
        "pva-glue",
        "PVA glue",
        "",
        "polymer",
        "liquid",
        WHITE,
        aliases=("white glue", "school glue"),
        roles=("polymer",),
    ),
    _c(
        "epoxy",
        "Epoxy resin",
        "",
        "polymer",
        "liquid",
        "#f5e9b8",
        hazards=("irritant",),
        roles=("binder",),
    ),
)

BY_ID: dict[str, Chemical] = {chemical.id: chemical for chemical in CHEMICALS}


def find(text: str) -> Chemical | None:
    """A shelf chemical by id, name, formula, or everyday name."""
    return _exact(text) or _partial(text)


def _exact(text: str) -> Chemical | None:
    wanted = text.strip().lower()
    if not wanted:
        return None
    if wanted in BY_ID:
        return BY_ID[wanted]
    for chemical in CHEMICALS:
        names = {chemical.name.lower(), chemical.formula.lower(), *chemical.aliases}
        base = chemical.name.lower().split(" (")[0]
        if wanted in names or wanted == base:
            return chemical
    return None


def _partial(text: str) -> Chemical | None:
    wanted = text.strip().lower()
    if len(wanted) < 3:
        return None
    for chemical in CHEMICALS:
        if wanted in chemical.name.lower() or any(
            wanted in alias for alias in chemical.aliases
        ):
            return chemical
    return None


def search(text: str, limit: int = 40) -> list[Chemical]:
    """Shelf chemicals whose names, formulas, or kinds contain the words."""
    words = text.lower().split()
    if not words:
        return list(CHEMICALS[:limit])
    found = [
        chemical
        for chemical in CHEMICALS
        if all(
            word
            in " ".join(
                (
                    chemical.name,
                    chemical.formula,
                    chemical.kind,
                    *chemical.aliases,
                    *chemical.roles,
                )
            ).lower()
            for word in words
        )
    ]
    return found[:limit]


# A typical molecule for shelf items with no single formula, so a bottle's
# element breakdown can still count them (shown as approximate).
TYPICAL: dict[str, str] = {
    "olive-oil": "C57H104O6",
    "coconut-oil": "C45H86O6",
    "sunflower-oil": "C57H98O6",
    "castor-oil": "C57H104O9",
    "mineral-oil": "C20H42",
    "shea-butter": "C57H110O6",
    "beeswax": "C46H92O2",
    "paraffin-wax": "C25H52",
    "soy-wax": "C57H110O6",
    "fragrance": "C10H18O",
    "peppermint-oil": "C10H20O",
    "xanthan-gum": "C35H49O29",
    "polyquaternium-10": "C12H24NO5",
    "aloe-vera": "H2O",
    "milk": "H2O",
    "dish-soap": "C16H33NaO6S",
    "pva-glue": "C2H4O",
    "epoxy": "C21H24O4",
    "hyaluronic-acid": "C14H20NNaO11",
    "starch": "C6H10O5",
    "yeast": "C6H12O6",
    "polysorbate-20": "C58H114O26",
    "emulsifying-wax": "C16H34O",
    "red-cabbage": "H2O",
    "universal-indicator": "H2O",
    "food-colouring-red": "H2O",
    "food-colouring-blue": "H2O",
    "food-colouring-yellow": "H2O",
}

_ELEMENT_COLOURS = {
    "alkali-metal": "#d9dde2",
    "alkaline-earth": "#dcdcd4",
    "transition": "#b0b6bd",
    "post-transition": "#c9ccd1",
    "lanthanide": "#c7c9c2",
    "actinide": "#9ea39a",
    "metalloid": "#8d949c",
    "nonmetal": "#e8f4ff",
    "halogen": "#d8e070",
    "noble-gas": "#f0e8ff",
}
_HALOGEN_COLOURS = {"F": "#f4f7c8", "Cl": "#c8e05a", "Br": "#8b2a10", "I": "#3a2140"}
_ACTIVE = {"Mg", "Al", "Zn", "Fe", "Sn", "Ni", "Pb", "Mn", "Cr", "Co", "Cd", "Ti"}


def element_chemical(symbol: str) -> Chemical | None:
    """Any element as a pure substance, for the ones the shelf lacks."""
    # Imported here: elements.py is data only and formula.py already uses it.
    from .elements import BY_SYMBOL

    element = BY_SYMBOL.get(symbol)
    if element is None:
        return None
    for chemical in CHEMICALS:
        if chemical.formula == symbol and chemical.kind in {"metal", "element"}:
            return chemical
    tags: set[str] = set()
    hazards: list[str] = []
    if element.category in {"alkali-metal"} or symbol in {"Ca", "Sr", "Ba"}:
        tags.add("very-active-metal")
        hazards += ["reactive-water", "flammable"]
    elif symbol in _ACTIVE:
        tags.add("active-metal")
    if element.category == "halogen":
        hazards += ["toxic", "oxidizer"] if symbol in {"F", "Cl", "Br"} else ["harmful"]
    if symbol == "I":
        tags.add("iodine")
    if symbol in {"P", "S", "C"}:
        tags.add("fuel")
        hazards.append("flammable")
    if symbol in {"As", "Hg", "Cd", "Tl", "Be", "Pb"}:
        hazards.append("toxic")
    if element.radioactive:
        hazards.append("radioactive")
    formula = {"H": "H2", "N": "N2", "O": "O2", "F": "F2", "Cl": "Cl2"}.get(
        symbol, symbol
    )
    if symbol in {"Br", "I"}:
        formula = f"{symbol}2"
    return Chemical(
        id=f"element-{symbol.lower()}",
        name=element.name,
        formula=formula,
        kind="metal"
        if "metal" in element.category
        or element.category
        in {
            "transition",
            "post-transition",
            "lanthanide",
            "actinide",
        }
        else "element",
        state=element.state if element.state != "unknown" else "solid",
        colour=_HALOGEN_COLOURS.get(symbol)
        or _ELEMENT_COLOURS.get(element.category, "#cccccc"),
        hazards=tuple(dict.fromkeys(hazards)),
        tags=frozenset(tags) | ({"insoluble"} if element.state == "solid" else set()),
        aliases=(symbol.lower(),),
        note=f"Pure {element.name.lower()} (element {element.number}).",
    )


def resolve(text: str) -> Chemical | None:
    """A shelf chemical, or any pure element by symbol or name."""
    from .elements import ELEMENTS

    wanted = text.strip()
    if wanted.lower() in BY_ID:
        return BY_ID[wanted.lower()]
    if wanted.lower().startswith("element-"):
        wanted = wanted[len("element-") :].title()
    by_symbol = {element.symbol: element for element in ELEMENTS}
    if wanted in by_symbol:
        return element_chemical(wanted)
    found = _exact(wanted)
    if found is not None:
        return found
    for element in ELEMENTS:
        if wanted.lower() == element.name.lower():
            return element_chemical(element.symbol)
    return _partial(wanted)
