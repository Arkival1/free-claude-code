"""The periodic table: all 118 elements, for the Lab's shelf and formulas.

Masses are standard atomic weights (the most stable isotope for elements
with none); group and period place each element on the table, with the
lanthanides and actinides drawn in their own rows below it.
"""

from dataclasses import dataclass

from . import LabData

# number, symbol, name, mass, category, group (0 = f-block), period, state
_TABLE = """
1 H Hydrogen 1.008 nonmetal 1 1 gas
2 He Helium 4.0026 noble-gas 18 1 gas
3 Li Lithium 6.94 alkali-metal 1 2 solid
4 Be Beryllium 9.0122 alkaline-earth 2 2 solid
5 B Boron 10.81 metalloid 13 2 solid
6 C Carbon 12.011 nonmetal 14 2 solid
7 N Nitrogen 14.007 nonmetal 15 2 gas
8 O Oxygen 15.999 nonmetal 16 2 gas
9 F Fluorine 18.998 halogen 17 2 gas
10 Ne Neon 20.180 noble-gas 18 2 gas
11 Na Sodium 22.990 alkali-metal 1 3 solid
12 Mg Magnesium 24.305 alkaline-earth 2 3 solid
13 Al Aluminium 26.982 post-transition 13 3 solid
14 Si Silicon 28.085 metalloid 14 3 solid
15 P Phosphorus 30.974 nonmetal 15 3 solid
16 S Sulfur 32.06 nonmetal 16 3 solid
17 Cl Chlorine 35.45 halogen 17 3 gas
18 Ar Argon 39.95 noble-gas 18 3 gas
19 K Potassium 39.098 alkali-metal 1 4 solid
20 Ca Calcium 40.078 alkaline-earth 2 4 solid
21 Sc Scandium 44.956 transition 3 4 solid
22 Ti Titanium 47.867 transition 4 4 solid
23 V Vanadium 50.942 transition 5 4 solid
24 Cr Chromium 51.996 transition 6 4 solid
25 Mn Manganese 54.938 transition 7 4 solid
26 Fe Iron 55.845 transition 8 4 solid
27 Co Cobalt 58.933 transition 9 4 solid
28 Ni Nickel 58.693 transition 10 4 solid
29 Cu Copper 63.546 transition 11 4 solid
30 Zn Zinc 65.38 transition 12 4 solid
31 Ga Gallium 69.723 post-transition 13 4 solid
32 Ge Germanium 72.630 metalloid 14 4 solid
33 As Arsenic 74.922 metalloid 15 4 solid
34 Se Selenium 78.971 nonmetal 16 4 solid
35 Br Bromine 79.904 halogen 17 4 liquid
36 Kr Krypton 83.798 noble-gas 18 4 gas
37 Rb Rubidium 85.468 alkali-metal 1 5 solid
38 Sr Strontium 87.62 alkaline-earth 2 5 solid
39 Y Yttrium 88.906 transition 3 5 solid
40 Zr Zirconium 91.224 transition 4 5 solid
41 Nb Niobium 92.906 transition 5 5 solid
42 Mo Molybdenum 95.95 transition 6 5 solid
43 Tc Technetium 98 transition 7 5 solid
44 Ru Ruthenium 101.07 transition 8 5 solid
45 Rh Rhodium 102.91 transition 9 5 solid
46 Pd Palladium 106.42 transition 10 5 solid
47 Ag Silver 107.87 transition 11 5 solid
48 Cd Cadmium 112.41 transition 12 5 solid
49 In Indium 114.82 post-transition 13 5 solid
50 Sn Tin 118.71 post-transition 14 5 solid
51 Sb Antimony 121.76 metalloid 15 5 solid
52 Te Tellurium 127.60 metalloid 16 5 solid
53 I Iodine 126.90 halogen 17 5 solid
54 Xe Xenon 131.29 noble-gas 18 5 gas
55 Cs Caesium 132.91 alkali-metal 1 6 solid
56 Ba Barium 137.33 alkaline-earth 2 6 solid
57 La Lanthanum 138.91 lanthanide 0 6 solid
58 Ce Cerium 140.12 lanthanide 0 6 solid
59 Pr Praseodymium 140.91 lanthanide 0 6 solid
60 Nd Neodymium 144.24 lanthanide 0 6 solid
61 Pm Promethium 145 lanthanide 0 6 solid
62 Sm Samarium 150.36 lanthanide 0 6 solid
63 Eu Europium 151.96 lanthanide 0 6 solid
64 Gd Gadolinium 157.25 lanthanide 0 6 solid
65 Tb Terbium 158.93 lanthanide 0 6 solid
66 Dy Dysprosium 162.50 lanthanide 0 6 solid
67 Ho Holmium 164.93 lanthanide 0 6 solid
68 Er Erbium 167.26 lanthanide 0 6 solid
69 Tm Thulium 168.93 lanthanide 0 6 solid
70 Yb Ytterbium 173.05 lanthanide 0 6 solid
71 Lu Lutetium 174.97 lanthanide 0 6 solid
72 Hf Hafnium 178.49 transition 4 6 solid
73 Ta Tantalum 180.95 transition 5 6 solid
74 W Tungsten 183.84 transition 6 6 solid
75 Re Rhenium 186.21 transition 7 6 solid
76 Os Osmium 190.23 transition 8 6 solid
77 Ir Iridium 192.22 transition 9 6 solid
78 Pt Platinum 195.08 transition 10 6 solid
79 Au Gold 196.97 transition 11 6 solid
80 Hg Mercury 200.59 transition 12 6 liquid
81 Tl Thallium 204.38 post-transition 13 6 solid
82 Pb Lead 207.2 post-transition 14 6 solid
83 Bi Bismuth 208.98 post-transition 15 6 solid
84 Po Polonium 209 post-transition 16 6 solid
85 At Astatine 210 halogen 17 6 solid
86 Rn Radon 222 noble-gas 18 6 gas
87 Fr Francium 223 alkali-metal 1 7 solid
88 Ra Radium 226 alkaline-earth 2 7 solid
89 Ac Actinium 227 actinide 0 7 solid
90 Th Thorium 232.04 actinide 0 7 solid
91 Pa Protactinium 231.04 actinide 0 7 solid
92 U Uranium 238.03 actinide 0 7 solid
93 Np Neptunium 237 actinide 0 7 solid
94 Pu Plutonium 244 actinide 0 7 solid
95 Am Americium 243 actinide 0 7 solid
96 Cm Curium 247 actinide 0 7 solid
97 Bk Berkelium 247 actinide 0 7 solid
98 Cf Californium 251 actinide 0 7 solid
99 Es Einsteinium 252 actinide 0 7 solid
100 Fm Fermium 257 actinide 0 7 solid
101 Md Mendelevium 258 actinide 0 7 solid
102 No Nobelium 259 actinide 0 7 solid
103 Lr Lawrencium 266 actinide 0 7 solid
104 Rf Rutherfordium 267 transition 4 7 unknown
105 Db Dubnium 268 transition 5 7 unknown
106 Sg Seaborgium 269 transition 6 7 unknown
107 Bh Bohrium 270 transition 7 7 unknown
108 Hs Hassium 277 transition 8 7 unknown
109 Mt Meitnerium 278 unknown 9 7 unknown
110 Ds Darmstadtium 281 unknown 10 7 unknown
111 Rg Roentgenium 282 unknown 11 7 unknown
112 Cn Copernicium 285 unknown 12 7 unknown
113 Nh Nihonium 286 unknown 13 7 unknown
114 Fl Flerovium 289 unknown 14 7 unknown
115 Mc Moscovium 290 unknown 15 7 unknown
116 Lv Livermorium 293 unknown 16 7 unknown
117 Ts Tennessine 294 unknown 17 7 unknown
118 Og Oganesson 294 unknown 18 7 unknown
"""

# Colours seen when a salt of the metal is held in a flame.
FLAME_COLOURS: dict[str, tuple[str, str]] = {
    "Li": ("crimson red", "#dc143c"),
    "Na": ("bright yellow-orange", "#ffb300"),
    "K": ("lilac", "#c8a2c8"),
    "Rb": ("red-violet", "#c71585"),
    "Cs": ("blue-violet", "#8a2be2"),
    "Ca": ("orange-red", "#ff5722"),
    "Sr": ("scarlet red", "#ff1a1a"),
    "Ba": ("pale apple green", "#9ccc65"),
    "Cu": ("blue-green", "#00bfa5"),
    "B": ("bright green", "#4caf50"),
    "Pb": ("pale blue-grey", "#90a4ae"),
    "Zn": ("bluish green", "#26a69a"),
    "Fe": ("gold sparks", "#ffca28"),
    "In": ("indigo blue", "#3f51b5"),
    "Se": ("azure blue", "#29b6f6"),
}

# A few facts shown on an element's card.
USES: dict[str, str] = {
    "H": "Fuel cells, making ammonia, and the Sun's fuel.",
    "He": "Balloons, MRI magnet cooling, and deep-sea diving gas.",
    "Li": "Rechargeable batteries in phones and electric cars.",
    "C": "Diamond, graphite pencils, steel, and all living things.",
    "N": "78% of air; fertilisers and food packaging.",
    "O": "21% of air; breathing, burning, and water.",
    "F": "Toothpaste (as fluoride) and non-stick coatings.",
    "Ne": "Glowing red-orange signs.",
    "Na": "Table salt, soap making (as lye), and street lamps.",
    "Mg": "Light alloys, fireworks' white sparks, and chlorophyll.",
    "Al": "Cans, foil, planes, and window frames.",
    "Si": "Computer chips, solar cells, glass, and sand.",
    "P": "Fertilisers, match heads, and DNA.",
    "S": "Sulfuric acid, rubber vulcanising, and matches.",
    "Cl": "Water treatment, PVC, and table salt.",
    "K": "Fertilisers and bananas.",
    "Ca": "Bones, teeth, chalk, and cement.",
    "Ti": "Strong light parts, implants, and white paint (TiO₂).",
    "Cr": "Stainless steel and shiny chrome plating.",
    "Fe": "Steel, the most used metal on Earth.",
    "Co": "Blue glass and battery cathodes.",
    "Ni": "Stainless steel, coins, and batteries.",
    "Cu": "Electrical wiring, pipes, and bronze.",
    "Zn": "Galvanising steel against rust, and batteries.",
    "Ga": "LEDs and melts in your hand (30 °C).",
    "Ge": "Fibre optics and early transistors.",
    "Br": "Flame retardants; one of two liquid elements.",
    "Ag": "Jewellery, mirrors, and the best electrical conductor.",
    "Sn": "Solder and tin-plated food cans.",
    "I": "Disinfectant and an essential nutrient in salt.",
    "W": "The highest melting metal: bulb filaments and drill bits.",
    "Pt": "Catalytic converters and jewellery.",
    "Au": "Jewellery and corrosion-free electronic contacts.",
    "Hg": "Old thermometers; a liquid metal (toxic).",
    "Pb": "Car batteries and radiation shielding (toxic).",
    "U": "Nuclear power fuel.",
}


@dataclass(frozen=True, slots=True)
class Element:
    number: int
    symbol: str
    name: str
    mass: float
    category: str
    group: int
    """0 for the lanthanides and actinides (drawn in their own rows)."""
    period: int
    state: str
    """At room temperature: solid, liquid, gas, or unknown."""

    @property
    def radioactive(self) -> bool:
        return self.number == 43 or self.number == 61 or self.number >= 84

    def view(self) -> LabData:
        flame = FLAME_COLOURS.get(self.symbol)
        return {
            "number": self.number,
            "symbol": self.symbol,
            "name": self.name,
            "mass": self.mass,
            "category": self.category,
            "group": self.group,
            "period": self.period,
            "state": self.state,
            "radioactive": self.radioactive,
            "flame": {"name": flame[0], "colour": flame[1]} if flame else None,
            "uses": USES.get(self.symbol, ""),
        }


def _load() -> tuple[Element, ...]:
    elements: list[Element] = []
    for line in _TABLE.strip().splitlines():
        number, symbol, name, mass, category, group, period, state = line.split()
        elements.append(
            Element(
                number=int(number),
                symbol=symbol,
                name=name,
                mass=float(mass),
                category=category,
                group=int(group),
                period=int(period),
                state=state,
            )
        )
    return tuple(elements)


ELEMENTS: tuple[Element, ...] = _load()
BY_SYMBOL: dict[str, Element] = {element.symbol: element for element in ELEMENTS}
