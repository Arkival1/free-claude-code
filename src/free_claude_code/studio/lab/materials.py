"""Materials to build with and test: metals, alloys, plastics, ceramics.

Properties are typical room-temperature handbook values. Blending
materials uses the known alloy when the recipe matches one, and the rule of
mixtures (with its honest limits) when it doesn't.
"""

from dataclasses import dataclass

from .data import LabData


@dataclass(frozen=True, slots=True)
class Material:
    id: str
    name: str
    category: str
    """metal, alloy, polymer, ceramic, composite, natural, semiconductor, glass."""
    colour: str
    density: float
    """g/cm³."""
    strength: float
    """Tensile strength, MPa."""
    stiffness: float
    """Young's modulus, GPa."""
    melts: float
    """Melting (or softening/decomposing) point, °C."""
    conducts_heat: float
    """Thermal conductivity, W/(m·K)."""
    resistivity: float
    """Electrical resistivity, Ω·m (large for insulators)."""
    hardness: float
    """Mohs scale."""
    stretch: float
    """Elongation at break, %."""
    rusts: str = "no"
    """no, slowly, yes."""
    composition: tuple[tuple[str, float], ...] = ()
    """Element or material ids with mass percentages, for alloys and blends."""
    uses: str = ""

    def view(self) -> LabData:
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "colour": self.colour,
            "density": self.density,
            "strength": self.strength,
            "stiffness": self.stiffness,
            "melts": self.melts,
            "conducts_heat": self.conducts_heat,
            "resistivity": self.resistivity,
            "conductor": self.resistivity < 1e-5,
            "hardness": self.hardness,
            "stretch": self.stretch,
            "rusts": self.rusts,
            "composition": [
                {"part": part, "percent": percent} for part, percent in self.composition
            ],
            "uses": self.uses,
        }


def _m(
    id: str,
    name: str,
    category: str,
    colour: str,
    density: float,
    strength: float,
    stiffness: float,
    melts: float,
    conducts_heat: float,
    resistivity: float,
    hardness: float,
    stretch: float,
    rusts: str = "no",
    composition: tuple[tuple[str, float], ...] = (),
    uses: str = "",
) -> Material:
    return Material(
        id,
        name,
        category,
        colour,
        density,
        strength,
        stiffness,
        melts,
        conducts_heat,
        resistivity,
        hardness,
        stretch,
        rusts,
        composition,
        uses,
    )


INSULATOR = 1e14

MATERIALS: tuple[Material, ...] = (
    # metals
    _m(
        "iron",
        "Iron (pure)",
        "metal",
        "#8a8d91",
        7.87,
        540,
        211,
        1538,
        80,
        9.7e-8,
        4,
        40,
        "yes",
        uses="Magnets' cores; the base of steel.",
    ),
    _m(
        "aluminium",
        "Aluminium",
        "metal",
        "#d6dbe0",
        2.70,
        90,
        69,
        660,
        237,
        2.65e-8,
        2.75,
        40,
        "no",
        uses="Cans, foil, light frames.",
    ),
    _m(
        "copper",
        "Copper",
        "metal",
        "#c46a3a",
        8.96,
        210,
        117,
        1085,
        401,
        1.68e-8,
        3,
        45,
        "slowly",
        uses="Wires and pipes: carries current and heat superbly.",
    ),
    _m(
        "titanium",
        "Titanium",
        "metal",
        "#9ea4a8",
        4.51,
        434,
        116,
        1668,
        22,
        4.2e-7,
        6,
        25,
        "no",
        uses="Aircraft, implants: strong and light.",
    ),
    _m(
        "gold",
        "Gold",
        "metal",
        "#f5c542",
        19.3,
        120,
        79,
        1064,
        318,
        2.44e-8,
        2.5,
        45,
        "no",
        uses="Connectors that never corrode.",
    ),
    _m(
        "silver",
        "Silver",
        "metal",
        "#e3e6ea",
        10.49,
        170,
        83,
        962,
        429,
        1.59e-8,
        2.5,
        45,
        "no",
        uses="Best conductor of all.",
    ),
    _m(
        "zinc",
        "Zinc",
        "metal",
        "#a9b0b8",
        7.14,
        110,
        108,
        420,
        116,
        5.9e-8,
        2.5,
        40,
        "no",
        uses="Galvanising and batteries.",
    ),
    _m(
        "tin",
        "Tin",
        "metal",
        "#bfc5c9",
        7.27,
        15,
        50,
        232,
        67,
        1.15e-7,
        1.5,
        60,
        "no",
        uses="Solder and plating.",
    ),
    _m(
        "nickel",
        "Nickel",
        "metal",
        "#9ca3a8",
        8.91,
        345,
        200,
        1455,
        91,
        6.99e-8,
        4,
        40,
        "no",
    ),
    _m(
        "magnesium",
        "Magnesium",
        "metal",
        "#c9ccd1",
        1.74,
        190,
        45,
        650,
        156,
        4.4e-8,
        2.5,
        8,
        "slowly",
        uses="The lightest structural metal.",
    ),
    _m(
        "lead",
        "Lead",
        "metal",
        "#6f7780",
        11.34,
        17,
        16,
        327,
        35,
        2.08e-7,
        1.5,
        50,
        "no",
        uses="Radiation shields (toxic).",
    ),
    _m(
        "tungsten",
        "Tungsten",
        "metal",
        "#8b8f93",
        19.25,
        980,
        411,
        3422,
        173,
        5.6e-8,
        7.5,
        2,
        "no",
        uses="Filaments and cutting tools.",
    ),
    _m(
        "chromium",
        "Chromium",
        "metal",
        "#c0c6cc",
        7.19,
        280,
        279,
        1907,
        94,
        1.25e-7,
        8.5,
        0,
        "no",
    ),
    _m(
        "manganese",
        "Manganese",
        "metal",
        "#9a9a9e",
        7.21,
        500,
        198,
        1246,
        8,
        1.44e-6,
        6,
        0,
        "slowly",
    ),
    _m(
        "vanadium",
        "Vanadium",
        "metal",
        "#9aa3aa",
        6.0,
        800,
        128,
        1910,
        31,
        1.97e-7,
        7,
        20,
        "no",
    ),
    _m(
        "antimony",
        "Antimony",
        "metal",
        "#a8adb3",
        6.68,
        11,
        55,
        631,
        24,
        4.17e-7,
        3,
        0,
        "no",
    ),
    _m(
        "graphite",
        "Graphite (carbon)",
        "ceramic",
        "#2e2e2e",
        2.26,
        20,
        10,
        3650,
        150,
        1e-5,
        1.5,
        0,
        "no",
        uses="Pencils, electrodes, and the carbon in steel.",
    ),
    _m(
        "lithium",
        "Lithium",
        "metal",
        "#c8ccd2",
        0.53,
        15,
        5,
        180,
        85,
        9.5e-8,
        0.6,
        50,
        "yes",
        uses="Battery anodes; floats on oil.",
    ),
    # alloys
    _m(
        "steel",
        "Mild steel",
        "alloy",
        "#8d9297",
        7.85,
        400,
        200,
        1450,
        50,
        1.43e-7,
        4.5,
        25,
        "yes",
        (("Fe", 99.75), ("C", 0.25)),
        "Beams, cars, nails.",
    ),
    _m(
        "high-carbon-steel",
        "High-carbon steel",
        "alloy",
        "#6f7479",
        7.85,
        900,
        205,
        1420,
        45,
        1.6e-7,
        6,
        8,
        "yes",
        (("Fe", 99.2), ("C", 0.8)),
        "Knives, springs, tools.",
    ),
    _m(
        "cast-iron",
        "Cast iron",
        "alloy",
        "#5a5d61",
        7.2,
        200,
        110,
        1200,
        55,
        1e-6,
        5,
        1,
        "yes",
        (("Fe", 96.5), ("C", 3.5)),
        "Pans and engine blocks: brittle.",
    ),
    _m(
        "stainless-steel",
        "Stainless steel (304)",
        "alloy",
        "#b8bec4",
        8.0,
        515,
        193,
        1400,
        16,
        7.2e-7,
        5.5,
        40,
        "no",
        (("Fe", 71), ("Cr", 18), ("Ni", 8), ("Mn", 2), ("C", 0.08), ("Si", 0.92)),
        "Sinks, cutlery: chromium stops rust.",
    ),
    _m(
        "brass",
        "Brass",
        "alloy",
        "#d4a84a",
        8.5,
        340,
        100,
        930,
        120,
        6.4e-8,
        3.5,
        50,
        "no",
        (("Cu", 63), ("Zn", 37)),
        "Instruments, fittings.",
    ),
    _m(
        "bronze",
        "Bronze",
        "alloy",
        "#b0773a",
        8.8,
        350,
        110,
        950,
        60,
        1.4e-7,
        3.5,
        20,
        "no",
        (("Cu", 88), ("Sn", 12)),
        "Statues, bells, bearings.",
    ),
    _m(
        "solder",
        "Solder (lead-free SAC305)",
        "alloy",
        "#c9cdd1",
        7.4,
        50,
        50,
        217,
        58,
        1.3e-7,
        1.5,
        30,
        "no",
        (("Sn", 96.5), ("Ag", 3), ("Cu", 0.5)),
        "Joins electronics.",
    ),
    _m(
        "solder-leaded",
        "Solder (tin-lead 63/37)",
        "alloy",
        "#b7bcc1",
        8.4,
        52,
        30,
        183,
        50,
        1.45e-7,
        1.5,
        30,
        "no",
        (("Sn", 63), ("Pb", 37)),
        "Older electronics (toxic lead).",
    ),
    _m(
        "duralumin",
        "Duralumin",
        "alloy",
        "#cfd4d9",
        2.78,
        450,
        73,
        640,
        150,
        3.5e-8,
        3,
        15,
        "no",
        (("Al", 94), ("Cu", 4.4), ("Mg", 1.5), ("Mn", 0.1)),
        "Aircraft frames.",
    ),
    _m(
        "sterling-silver",
        "Sterling silver",
        "alloy",
        "#dde1e5",
        10.36,
        250,
        72,
        893,
        360,
        2e-8,
        3,
        30,
        "slowly",
        (("Ag", 92.5), ("Cu", 7.5)),
        "Jewellery and cutlery.",
    ),
    _m(
        "gold-18k",
        "18k gold",
        "alloy",
        "#e8b93a",
        15.6,
        350,
        80,
        900,
        100,
        1.4e-7,
        3,
        30,
        "no",
        (("Au", 75), ("Ag", 12.5), ("Cu", 12.5)),
        "Jewellery: harder than pure gold.",
    ),
    _m(
        "nitinol",
        "Nitinol (shape memory)",
        "alloy",
        "#a4a8ab",
        6.45,
        900,
        75,
        1310,
        18,
        8.2e-7,
        6,
        15,
        "no",
        (("Ni", 55), ("Ti", 45)),
        "Springs back to shape when warmed.",
    ),
    _m(
        "invar",
        "Invar",
        "alloy",
        "#9ca1a6",
        8.05,
        480,
        141,
        1427,
        10,
        8.2e-7,
        4,
        30,
        "slowly",
        (("Fe", 64), ("Ni", 36)),
        "Barely expands with heat: clocks, instruments.",
    ),
    _m(
        "pewter",
        "Pewter",
        "alloy",
        "#a8adb2",
        7.28,
        40,
        53,
        240,
        50,
        1.4e-7,
        1.5,
        40,
        "no",
        (("Sn", 92), ("Sb", 6), ("Cu", 2)),
        "Tankards and figures.",
    ),
    _m(
        "titanium-6al4v",
        "Titanium Ti-6Al-4V",
        "alloy",
        "#9aa0a5",
        4.43,
        950,
        114,
        1660,
        7,
        1.7e-6,
        6,
        14,
        "no",
        (("Ti", 90), ("Al", 6), ("V", 4)),
        "Jet parts and implants.",
    ),
    _m(
        "nichrome",
        "Nichrome",
        "alloy",
        "#8f949a",
        8.4,
        700,
        220,
        1400,
        11,
        1.1e-6,
        6,
        30,
        "no",
        (("Ni", 80), ("Cr", 20)),
        "Heating elements: resists current and glows.",
    ),
    # polymers
    _m(
        "pla",
        "PLA plastic",
        "polymer",
        "#f0f0f0",
        1.24,
        50,
        3.5,
        160,
        0.13,
        INSULATOR,
        2,
        6,
        uses="3D printing (softens at 60 °C).",
    ),
    _m(
        "abs",
        "ABS plastic",
        "polymer",
        "#eeeeee",
        1.05,
        40,
        2.3,
        210,
        0.17,
        INSULATOR,
        2,
        20,
        uses="LEGO bricks, cases.",
    ),
    _m(
        "petg",
        "PETG plastic",
        "polymer",
        "#dff3ff",
        1.27,
        50,
        2.1,
        230,
        0.2,
        INSULATOR,
        2,
        25,
        uses="Tough 3D prints, bottles.",
    ),
    _m(
        "nylon",
        "Nylon 6,6",
        "polymer",
        "#f4f1e8",
        1.14,
        80,
        3,
        264,
        0.25,
        INSULATOR,
        2.5,
        60,
        uses="Gears, rope, clothing.",
    ),
    _m(
        "polycarbonate",
        "Polycarbonate",
        "polymer",
        "#e8f6ff",
        1.2,
        65,
        2.4,
        225,
        0.2,
        INSULATOR,
        2.5,
        110,
        uses="Shatter-proof windows, visors.",
    ),
    _m(
        "acrylic",
        "Acrylic (PMMA)",
        "polymer",
        "#e9f7ff",
        1.18,
        70,
        3.2,
        160,
        0.19,
        INSULATOR,
        3,
        5,
        uses="Clear display cases.",
    ),
    _m(
        "pvc",
        "PVC",
        "polymer",
        "#dfe3e6",
        1.38,
        50,
        3,
        100,
        0.19,
        INSULATOR,
        2.5,
        40,
        uses="Pipes and cable coating.",
    ),
    _m(
        "hdpe",
        "HDPE",
        "polymer",
        "#fafafa",
        0.95,
        30,
        1,
        130,
        0.48,
        INSULATOR,
        2,
        500,
        uses="Milk jugs, chopping boards.",
    ),
    _m(
        "silicone",
        "Silicone rubber",
        "polymer",
        "#f0e6ff",
        1.1,
        8,
        0.005,
        300,
        0.2,
        INSULATOR,
        1,
        400,
        uses="Seals, baking moulds, phone cases.",
    ),
    _m(
        "rubber",
        "Natural rubber",
        "polymer",
        "#3a3a3a",
        0.92,
        25,
        0.01,
        180,
        0.13,
        INSULATOR,
        1,
        700,
        uses="Tyres and bands.",
    ),
    _m(
        "kevlar",
        "Kevlar fibre",
        "polymer",
        "#e6c24a",
        1.44,
        3620,
        112,
        500,
        0.04,
        INSULATOR,
        3,
        3.6,
        uses="Body armour and ropes.",
    ),
    _m(
        "ptfe",
        "PTFE (Teflon)",
        "polymer",
        "#fcfcfc",
        2.2,
        25,
        0.5,
        327,
        0.25,
        INSULATOR,
        1.5,
        300,
        uses="Non-stick pans, low-friction parts.",
    ),
    _m(
        "epoxy",
        "Epoxy resin",
        "polymer",
        "#f5e9b8",
        1.2,
        60,
        3,
        150,
        0.2,
        INSULATOR,
        3,
        4,
        uses="Glue and composite matrix.",
    ),
    # ceramics & glass
    _m(
        "glass",
        "Soda-lime glass",
        "glass",
        "#d9f2f2",
        2.5,
        45,
        70,
        1000,
        1,
        INSULATOR,
        5.5,
        0,
        uses="Windows and bottles: brittle.",
    ),
    _m(
        "borosilicate",
        "Borosilicate glass",
        "glass",
        "#e0f7f7",
        2.23,
        60,
        64,
        820,
        1.2,
        INSULATOR,
        6,
        0,
        uses="Lab glass: survives heat shock.",
    ),
    _m(
        "alumina",
        "Alumina ceramic",
        "ceramic",
        "#fbfbf6",
        3.95,
        300,
        370,
        2072,
        30,
        INSULATOR,
        9,
        0,
        uses="Spark plugs, armour.",
    ),
    _m(
        "silicon-carbide",
        "Silicon carbide",
        "ceramic",
        "#3c4a4f",
        3.21,
        400,
        410,
        2730,
        120,
        1e3,
        9.5,
        0,
        uses="Brake discs, power chips.",
    ),
    _m(
        "concrete",
        "Concrete",
        "ceramic",
        "#a7a39a",
        2.4,
        3,
        30,
        1500,
        1.7,
        1e2,
        5,
        0,
        uses="Buildings (strong squeezed, weak pulled).",
    ),
    _m(
        "porcelain",
        "Porcelain",
        "ceramic",
        "#fbfbfb",
        2.4,
        50,
        70,
        1400,
        1.5,
        INSULATOR,
        7,
        0,
        uses="Cups and insulators.",
    ),
    _m(
        "diamond",
        "Diamond",
        "ceramic",
        "#e8fbff",
        3.51,
        2800,
        1050,
        3550,
        2200,
        INSULATOR,
        10,
        0,
        uses="The hardest natural material.",
    ),
    _m(
        "graphene",
        "Graphene",
        "composite",
        "#2b2b2b",
        2.27,
        130000,
        1000,
        3650,
        5000,
        1e-8,
        8,
        25,
        uses="One atom thick, the strongest material measured.",
    ),
    # composites & natural
    _m(
        "carbon-fibre",
        "Carbon fibre (epoxy composite)",
        "composite",
        "#1f1f1f",
        1.6,
        600,
        70,
        300,
        5,
        1e-4,
        5,
        1.5,
        uses="Bikes, cars, drones.",
    ),
    _m(
        "fibreglass",
        "Fibreglass",
        "composite",
        "#e9eadb",
        1.9,
        250,
        25,
        300,
        0.3,
        INSULATOR,
        5,
        2,
        uses="Boats and circuit boards (FR-4).",
    ),
    _m(
        "wood-oak",
        "Oak wood",
        "natural",
        "#a0703e",
        0.75,
        90,
        11,
        300,
        0.17,
        1e12,
        3,
        1.5,
        "slowly",
        uses="Furniture and floors (rots if wet).",
    ),
    _m(
        "wood-pine",
        "Pine wood",
        "natural",
        "#d6b37a",
        0.5,
        70,
        9,
        300,
        0.12,
        1e12,
        2,
        1.5,
        "slowly",
        uses="Framing timber.",
    ),
    _m(
        "bamboo",
        "Bamboo",
        "natural",
        "#c9b16b",
        0.7,
        180,
        18,
        300,
        0.2,
        1e12,
        3,
        2,
        "slowly",
        uses="Scaffolding: stronger than steel by weight.",
    ),
    _m(
        "cotton",
        "Cotton",
        "natural",
        "#fbfbf5",
        1.54,
        400,
        8,
        250,
        0.06,
        1e12,
        1,
        7,
        uses="Clothing.",
    ),
    _m(
        "spider-silk",
        "Spider silk",
        "natural",
        "#f7f7f0",
        1.3,
        1100,
        10,
        250,
        0.3,
        1e12,
        1,
        30,
        uses="Stronger than steel for its weight.",
    ),
    _m("bone", "Bone", "natural", "#efe8d8", 1.9, 130, 18, 1000, 0.3, 1e6, 3.5, 2),
    _m(
        "silicon",
        "Silicon (crystal)",
        "semiconductor",
        "#5b6770",
        2.33,
        150,
        130,
        1414,
        150,
        1e3,
        7,
        0,
        uses="Computer chips and solar cells.",
    ),
    _m(
        "gallium-arsenide",
        "Gallium arsenide",
        "semiconductor",
        "#4d5560",
        5.32,
        85,
        85,
        1238,
        55,
        1e6,
        4.5,
        0,
        uses="LEDs, lasers, solar cells in space.",
    ),
)

BY_ID: dict[str, Material] = {material.id: material for material in MATERIALS}
_ELEMENT_METALS = {
    "Fe": "iron",
    "Al": "aluminium",
    "Cu": "copper",
    "Ti": "titanium",
    "Au": "gold",
    "Ag": "silver",
    "Zn": "zinc",
    "Sn": "tin",
    "Ni": "nickel",
    "Mg": "magnesium",
    "Pb": "lead",
    "W": "tungsten",
    "Cr": "chromium",
    "Li": "lithium",
    "Mn": "manganese",
    "V": "vanadium",
    "Sb": "antimony",
    "C": "graphite",
    "Si": "silicon",
}


def find(text: str) -> Material | None:
    wanted = text.strip().lower()
    if wanted in BY_ID:
        return BY_ID[wanted]
    if text.strip() in _ELEMENT_METALS:
        return BY_ID[_ELEMENT_METALS[text.strip()]]
    for material in MATERIALS:
        if wanted in {material.name.lower(), material.name.lower().split(" (")[0]}:
            return material
    for material in MATERIALS:
        if len(wanted) >= 3 and wanted in material.name.lower():
            return material
    return None


def _symbol(material: Material) -> str | None:
    for symbol, material_id in _ELEMENT_METALS.items():
        if material_id == material.id:
            return symbol
    return None


def _tolerance(percent: float) -> float:
    return max(4.0, percent * 0.15) if percent >= 10 else max(0.3, percent * 0.3)


def blend(parts: list[LabData]) -> LabData:
    """Combine materials by mass percent: a known alloy, or an estimate."""
    chosen: list[tuple[Material, float]] = []
    for part in parts:
        material = find(str(part.get("id") or part.get("name") or ""))
        if material is None:
            raise ValueError(
                f"No material called {part.get('id') or part.get('name')!r}."
            )
        raw = part.get("percent")
        share = float(raw) if isinstance(raw, int | float) else 0.0
        chosen.append((material, share))
    if not chosen:
        raise ValueError("Pick at least one material.")
    total = sum(share for _, share in chosen) or float(len(chosen))
    if all(share == 0 for _, share in chosen):
        chosen = [(material, 1.0) for material, _ in chosen]
    shares = [(material, share / total * 100) for material, share in chosen]
    wanted = {_symbol(material) or material.id: share for material, share in shares}
    for material in MATERIALS:
        if not material.composition:
            continue
        recipe = dict(material.composition)
        main = {key for key, value in recipe.items() if value >= 1}
        if main <= set(wanted) <= set(recipe) and all(
            abs(recipe[key] - share) <= _tolerance(recipe[key])
            for key, share in wanted.items()
        ):
            return {
                "material": material.view(),
                "known": True,
                "note": f"That recipe is {material.name}: a real, well-tested alloy.",
                "tests": run_tests(material),
            }
    # The rule of mixtures: a first estimate, not a promise.
    volumes = [(material, share / material.density) for material, share in shares]
    volume = sum(v for _, v in volumes)
    fractions = [(material, v / volume) for material, v in volumes]
    density = 100 / volume
    stiffness = sum(material.stiffness * f for material, f in fractions)
    strength = sum(material.strength * f for material, f in fractions)
    conducts = sum(material.conducts_heat * f for material, f in fractions)
    resistivity = 1 / sum(f / material.resistivity for material, f in fractions)
    categories = {material.category for material, _ in shares}
    metals_only = categories <= {"metal", "alloy"}
    if metals_only and len(shares) > 1:
        # Alloying hardens metals (solid-solution strengthening) and
        # scatters electrons (higher resistance).
        strength *= 1.3
        resistivity *= 2.5
        conducts *= 0.6
    melts = (
        min(material.melts for material, _ in shares)
        if not metals_only
        else sum(material.melts * share / 100 for material, share in shares) * 0.95
    )
    colour_parts = [(material.colour, share) for material, share in shares]
    from .sim import blend as blend_colour

    colour, _ = blend_colour(colour_parts)
    name = "-".join(material.name.split(" (")[0] for material, _ in shares) + (
        " alloy" if metals_only else " composite"
    )
    made = Material(
        id="custom",
        name=name,
        category="alloy" if metals_only else "composite",
        colour=colour,
        density=round(density, 3),
        strength=round(strength, 1),
        stiffness=round(stiffness, 1),
        melts=round(melts),
        conducts_heat=round(conducts, 2),
        resistivity=resistivity,
        hardness=round(max(material.hardness for material, _ in shares), 1),
        stretch=round(min(material.stretch for material, _ in shares), 1),
        rusts="yes"
        if any(material.rusts == "yes" and share > 50 for material, share in shares)
        else "no",
        composition=tuple(
            (_symbol(material) or material.id, round(share, 2))
            for material, share in shares
        ),
    )
    note = (
        "A new blend: estimated with the rule of mixtures. Real alloys and "
        "composites can be stronger or weaker than this, so test a sample."
    )
    if not metals_only and categories & {"metal", "alloy"}:
        note += " Metals and non-metals don't melt together: this is a composite."
    return {
        "material": made.view(),
        "known": False,
        "note": note,
        "tests": run_tests(made),
    }


def run_tests(material: Material) -> LabData:
    """What a sample does in the Lab's test rigs, for the animations."""
    strain_break = max(material.stretch, 0.05) / 100
    yield_strain = (
        material.strength / (material.stiffness * 1000) if material.stiffness else 0.01
    )
    points = []
    for step in range(11):
        strain = strain_break * step / 10
        if strain <= yield_strain:
            stress = material.stiffness * 1000 * strain
        else:
            stress = material.strength * (0.85 + 0.15 * min(1.0, strain / strain_break))
        points.append(
            {
                "strain_percent": round(strain * 100, 3),
                "stress_mpa": round(min(stress, material.strength), 1),
            }
        )
    specific = material.strength / material.density
    return {
        "pull": {
            "breaks_at_mpa": material.strength,
            "stretch_percent": material.stretch,
            "brittle": material.stretch < 2,
            "curve": points,
            "word": "snaps suddenly"
            if material.stretch < 2
            else "stretches, necks, then tears",
        },
        "float": {
            "floats_in_water": material.density < 1.0,
            "text": "Floats" if material.density < 1 else "Sinks",
        },
        "heat": {
            "melts_c": material.melts,
            "in_kitchen_oven": material.melts > 250,
            "text": f"Melts or breaks down around {material.melts:.0f} °C.",
        },
        "electric": {
            "conductor": material.resistivity < 1e-5,
            "semiconductor": 1e-5 <= material.resistivity < 1e7,
            "resistivity": material.resistivity,
            "bulb": "bright"
            if material.resistivity < 1e-6
            else "dim"
            if material.resistivity < 1e-3
            else "off",
        },
        "scratch": {
            "mohs": material.hardness,
            "text": "Scratches glass"
            if material.hardness > 5.5
            else "Glass scratches it",
        },
        "rust": {"rusts": material.rusts},
        "strength_to_weight": round(specific, 1),
    }
