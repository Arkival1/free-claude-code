"""Products the Lab can make: real formulas with every ingredient listed.

A product is a list of shelf chemicals with mass percentages. Building one
works out the grams for a batch, the colour in the bottle, each
ingredient's molecule, and what the whole product is made of element by
element. Tech builds are lists of parts for the circuit bench.
"""

import re
from collections import defaultdict

from . import LabData
from .chemicals import TYPICAL, Chemical, resolve
from .elements import BY_SYMBOL
from .formula import FormulaError, parse
from .sim import blend

# Each ingredient: (shelf id, percent or None for "water to 100%", purpose).
Formula = tuple[tuple[str, float | None, str], ...]

PRODUCTS: dict[str, LabData] = {
    "shampoo": {
        "name": "Shampoo",
        "container": "bottle",
        "batch_g": 250,
        "ph": "5.0-5.5",
        "ingredients": (
            ("water", None, "Base that everything dissolves in"),
            ("sles", 30.0, "Main cleanser: lifts oil and dirt (25% active)"),
            ("capb", 8.0, "Mild co-cleanser: richer, gentler foam"),
            ("glycerol", 2.0, "Keeps hair and scalp from drying out"),
            ("panthenol", 1.0, "Pro-vitamin B5: softness and shine"),
            ("polyquaternium-10", 0.3, "Conditioning polymer: less tangling"),
            ("sodium-chloride", 1.2, "Thickens the shampoo"),
            ("citric-acid", 0.3, "Brings the pH down to hair-friendly 5.5"),
            ("disodium-edta", 0.1, "Stops hard water minerals dulling hair"),
            ("phenoxyethanol", 0.8, "Preservative: stops mould and bacteria"),
            ("fragrance", 0.5, "Scent"),
        ),
        "steps": (
            "Weigh the water into a clean beaker.",
            "Sprinkle in the polyquaternium-10 and stir until clear (10 min).",
            "Stir in the SLES and cocamidopropyl betaine slowly so it doesn't foam.",
            "Add glycerin, panthenol, EDTA, preservative, and fragrance.",
            "Check the pH and adjust to 5.0-5.5 with the citric acid.",
            "Thicken with salt a little at a time (too much makes it thin again).",
            "Leave the bubbles to rise overnight, then bottle it.",
        ),
    },
    "conditioner": {
        "name": "Hair conditioner",
        "container": "bottle",
        "batch_g": 250,
        "ph": "4.0-4.5",
        "ingredients": (
            ("water", None, "Base"),
            ("cetearyl-alcohol", 5.0, "Fatty alcohol: creamy thickness and slip"),
            ("emulsifying-wax", 3.0, "Holds the oil and water together"),
            ("glycerol", 2.0, "Moisture"),
            ("panthenol", 1.0, "Softness and shine"),
            ("coconut-oil", 1.0, "Smooths the hair cuticle"),
            ("polyquaternium-10", 0.5, "Detangling"),
            ("phenoxyethanol", 0.8, "Preservative"),
            ("citric-acid", 0.2, "pH 4-4.5 to smooth the cuticle"),
            ("fragrance", 0.4, "Scent"),
        ),
        "steps": (
            "Heat the water phase and the oil phase (waxes, oil) separately to 70 °C.",
            "Pour the oil phase into the water phase while blending.",
            "Stir as it cools; below 40 °C add panthenol, preservative, and fragrance.",
            "Adjust the pH to 4-4.5.",
        ),
    },
    "body-wash": {
        "name": "Body wash",
        "container": "pump",
        "batch_g": 300,
        "ph": "5.5-6",
        "ingredients": (
            ("water", None, "Base"),
            ("sles", 25.0, "Main cleanser"),
            ("capb", 7.0, "Mild co-cleanser"),
            ("decyl-glucoside", 5.0, "Plant-based gentle cleanser"),
            ("glycerol", 3.0, "Moisture"),
            ("aloe-vera", 2.0, "Soothing"),
            ("sodium-chloride", 1.5, "Thickener"),
            ("citric-acid", 0.3, "pH"),
            ("phenoxyethanol", 0.8, "Preservative"),
            ("fragrance", 0.8, "Scent"),
        ),
        "steps": (
            "Mix the cleansers into the water gently.",
            "Add the rest, adjust the pH, thicken with salt.",
        ),
    },
    "hand-soap": {
        "name": "Liquid hand soap",
        "container": "pump",
        "batch_g": 300,
        "ph": "5.5-6.5",
        "ingredients": (
            ("water", None, "Base"),
            ("decyl-glucoside", 15.0, "Gentle cleanser"),
            ("capb", 6.0, "Foam"),
            ("glycerol", 3.0, "Keeps hands soft"),
            ("aloe-vera", 2.0, "Soothing"),
            ("xanthan-gum", 0.4, "Thickener"),
            ("citric-acid", 0.2, "pH"),
            ("phenoxyethanol", 0.8, "Preservative"),
            ("fragrance", 0.5, "Scent"),
        ),
        "steps": (
            "Disperse the xanthan in the glycerin, then whisk into the water.",
            "Stir in everything else.",
        ),
    },
    "bar-soap": {
        "name": "Bar soap (cold process)",
        "container": "bar",
        "batch_g": 1500,
        "ph": "9-10",
        "ingredients": (
            ("olive-oil", 30.0, "Gentle, conditioning bar"),
            ("coconut-oil", 20.0, "Big bubbly lather and hardness"),
            ("shea-butter", 13.3, "Creamy, moisturising"),
            ("castor-oil", 3.3, "Stable lather"),
            (
                "sodium-hydroxide-solid",
                9.4,
                "Lye: turns the oils into soap (5% superfat)",
            ),
            ("water", None, "Dissolves the lye"),
            ("fragrance", 2.0, "Scent"),
        ),
        "steps": (
            "Goggles and gloves on. Add the lye to the water (never water to lye) and let it cool.",
            "Melt the shea and coconut, add the liquid oils.",
            "At about 40 °C pour the lye into the oils and stick-blend to 'trace'.",
            "Stir in fragrance, pour into a mould, and insulate for 24-48 hours.",
            "Cut into bars and cure for 4-6 weeks: the lye is all used up by then.",
        ),
        "safety": "Lye burns skin and eyes. The finished, cured soap is safe.",
        "reaction": ("olive-oil", "sodium-hydroxide"),
    },
    "toothpaste": {
        "name": "Toothpaste",
        "container": "tube",
        "batch_g": 100,
        "ph": "7-8",
        "ingredients": (
            ("calcium-carbonate", 38.0, "Gentle abrasive: polishes teeth"),
            ("water", None, "Base"),
            ("glycerol", 12.0, "Stops it drying out"),
            ("sorbitol", 12.0, "Moisture and a sweet taste"),
            ("sls", 1.5, "Foam that spreads it round your mouth"),
            ("xanthan-gum", 1.0, "Binder: makes the paste"),
            (
                "sodium-fluoride",
                0.32,
                "Fluoride (1450 ppm): hardens enamel, prevents cavities",
            ),
            ("sodium-saccharin", 0.2, "Sweetener"),
            ("peppermint-oil", 1.0, "Minty flavour"),
            ("titanium-dioxide", 0.5, "Bright white colour"),
            ("sodium-benzoate", 0.3, "Preservative"),
        ),
        "steps": (
            "Mix the gum into glycerin and sorbitol.",
            "Add water, then the powders, and mix to a smooth paste.",
            "Add flavour and fill the tube.",
        ),
        "safety": "Fluoride toothpaste: spit, don't swallow. Children use a pea-sized amount.",
    },
    "hand-sanitizer": {
        "name": "Hand sanitiser (WHO formula)",
        "container": "spray",
        "batch_g": 250,
        "ph": "about 7",
        "ingredients": (
            ("ethanol", 83.3, "Kills germs (80% alcohol in the final mix)"),
            ("hydrogen-peroxide", 4.17, "Kills bacterial spores in the bottle"),
            ("glycerol", 1.45, "Protects skin from drying"),
            ("water", None, "Makes up the volume"),
        ),
        "steps": (
            "Mix in this order in a closed container.",
            "Leave 72 hours before use so any spores are killed.",
        ),
        "safety": "Flammable until dry. Keep away from flames and children.",
    },
    "lotion": {
        "name": "Body lotion",
        "container": "pump",
        "batch_g": 250,
        "ph": "5-6",
        "ingredients": (
            ("water", None, "Water phase"),
            ("sunflower-oil", 12.0, "Softens skin"),
            ("shea-butter", 5.0, "Rich moisture"),
            ("emulsifying-wax", 5.0, "Holds oil and water together"),
            ("cetearyl-alcohol", 2.0, "Body and a silky feel"),
            ("glycerol", 3.0, "Draws in moisture"),
            ("aloe-vera", 5.0, "Soothing"),
            ("vitamin-e", 0.5, "Antioxidant: keeps the oils fresh"),
            ("xanthan-gum", 0.2, "Stabiliser"),
            ("phenoxyethanol", 0.8, "Preservative"),
            ("fragrance", 0.3, "Scent"),
        ),
        "steps": (
            "Heat the water and oil phases to 70 °C.",
            "Blend them together.",
            "Cool to 40 °C and add the rest.",
        ),
    },
    "lip-balm": {
        "name": "Lip balm",
        "container": "tube",
        "batch_g": 50,
        "ph": "no water",
        "ingredients": (
            ("beeswax", 30.0, "Firmness"),
            ("shea-butter", 30.0, "Soft, moisturising"),
            ("coconut-oil", 35.0, "Glide"),
            ("sunflower-oil", 3.0, "Softness"),
            ("vitamin-e", 1.0, "Keeps it fresh"),
            ("peppermint-oil", 1.0, "Tingle and flavour"),
        ),
        "steps": (
            "Melt everything gently.",
            "Add the peppermint off the heat and pour into tubes.",
        ),
    },
    "dish-soap": {
        "name": "Dish soap",
        "container": "bottle",
        "batch_g": 500,
        "ph": "6-7",
        "ingredients": (
            ("water", None, "Base"),
            ("sles", 30.0, "Grease cutter"),
            ("capb", 5.0, "Foam booster"),
            ("sodium-chloride", 2.0, "Thickener"),
            ("citric-acid", 0.2, "pH"),
            ("phenoxyethanol", 0.5, "Preservative"),
            ("fragrance", 0.3, "Lemon scent"),
            ("food-colouring-yellow", 0.05, "Colour"),
        ),
        "steps": (
            "Stir the surfactants into the water.",
            "Add the rest and thicken with salt.",
        ),
    },
    "bath-bomb": {
        "name": "Bath bomb",
        "container": "ball",
        "batch_g": 200,
        "ph": "fizzes to about 6",
        "ingredients": (
            ("sodium-bicarbonate", 50.0, "Base: fizzes with the citric acid in water"),
            ("citric-acid", 25.0, "Acid: fizzes with the baking soda"),
            ("starch", 12.0, "Slows the fizz so it lasts"),
            ("magnesium-sulfate", 8.0, "Epsom salt: bath salt"),
            ("coconut-oil", 3.5, "Binds it and softens skin"),
            ("fragrance", 1.0, "Scent"),
            ("food-colouring-red", 0.5, "Colour"),
        ),
        "steps": (
            "Mix the powders.",
            "Mix oil, scent, and colour; add drop by drop until it holds like damp sand.",
            "Pack into moulds and dry for 24 hours.",
        ),
        "reaction": ("water", "sodium-bicarbonate", "citric-acid"),
    },
    "slime": {
        "name": "Slime",
        "container": "jar",
        "batch_g": 200,
        "ph": "about 9",
        "ingredients": (
            ("pva-glue", 50.0, "Long polymer chains"),
            ("water", None, "Makes it stretchy"),
            ("borax", 1.0, "Borate ions link the chains into a gel"),
            ("food-colouring-blue", 0.5, "Colour"),
        ),
        "steps": (
            "Mix glue, half the water, and colour.",
            "Dissolve the borax in the rest of the water and stir it in a little at a time.",
        ),
        "safety": "Borax: wash hands after, and don't eat it.",
        "reaction": ("pva-glue", "borax", "water"),
    },
    "candle": {
        "name": "Scented candle",
        "container": "candle",
        "batch_g": 200,
        "ph": "no water",
        "ingredients": (
            ("soy-wax", 92.0, "Burns cleanly and slowly"),
            ("fragrance", 8.0, "Scent throw"),
        ),
        "steps": (
            "Melt the wax to 85 °C.",
            "Cool to 65 °C, stir in the fragrance for 2 minutes.",
            "Pour round a wick and cure for a week.",
        ),
        "safety": "Never leave a burning candle alone.",
    },
    "perfume": {
        "name": "Perfume (eau de parfum)",
        "container": "spray",
        "batch_g": 50,
        "ph": "about 7",
        "ingredients": (
            ("ethanol", 78.0, "Carries the scent"),
            ("fragrance", 18.0, "The perfume oils (EDP strength)"),
            ("water", None, "Softens the alcohol"),
        ),
        "steps": (
            "Mix the oils into the alcohol.",
            "Add the water, then let it mature 2-4 weeks in the dark.",
        ),
        "safety": "Flammable.",
    },
    "sunscreen": {
        "name": "Mineral sun cream",
        "container": "tube",
        "batch_g": 100,
        "ph": "6-7",
        "ingredients": (
            ("water", None, "Water phase"),
            ("zinc-oxide", 20.0, "Mineral UV filter: reflects and absorbs UVA and UVB"),
            ("sunflower-oil", 15.0, "Spreads the zinc evenly"),
            ("emulsifying-wax", 6.0, "Emulsifier"),
            ("shea-butter", 5.0, "Moisture"),
            ("glycerol", 3.0, "Moisture"),
            ("vitamin-e", 0.5, "Antioxidant"),
            ("phenoxyethanol", 0.8, "Preservative"),
        ),
        "steps": (
            "Disperse the zinc in the oil.",
            "Emulsify with the water phase at 70 °C.",
        ),
        "safety": "Home-made sun cream can't be trusted without an SPF lab test: use tested sunscreen outdoors.",
    },
    "glass-cleaner": {
        "name": "Glass cleaner",
        "container": "spray",
        "batch_g": 500,
        "ph": "about 3",
        "ingredients": (
            ("water", None, "Base"),
            ("isopropanol", 20.0, "Dissolves grease, dries streak-free"),
            ("acetic-acid", 10.0, "Vinegar: cuts hard-water spots"),
            ("dish-soap", 0.1, "Wets the glass"),
        ),
        "steps": ("Mix in a spray bottle.",),
        "safety": "Never mix with bleach.",
    },
    "elephant-toothpaste": {
        "name": "Elephant toothpaste (demo)",
        "container": "flask",
        "batch_g": 100,
        "ph": "about 7",
        "ingredients": (
            ("hydrogen-peroxide", 60.0, "Breaks down into oxygen"),
            ("dish-soap", 10.0, "Traps the oxygen as foam"),
            ("potassium-iodide", 20.0, "Catalyst: speeds the breakdown"),
            ("food-colouring-red", 1.0, "Colour"),
            ("water", None, ""),
        ),
        "steps": (
            "Stand the flask in a tray.",
            "Mix peroxide, soap, and colour; pour in the catalyst and step back.",
        ),
        "reaction": ("hydrogen-peroxide", "dish-soap", "potassium-iodide"),
    },
}

ALIASES = {
    "hair wash": "shampoo",
    "shower gel": "body-wash",
    "soap": "bar-soap",
    "hand wash": "hand-soap",
    "liquid soap": "hand-soap",
    "sanitizer": "hand-sanitizer",
    "sanitiser": "hand-sanitizer",
    "hand sanitiser": "hand-sanitizer",
    "moisturiser": "lotion",
    "moisturizer": "lotion",
    "cream": "lotion",
    "chapstick": "lip-balm",
    "washing up liquid": "dish-soap",
    "detergent": "dish-soap",
    "sun cream": "sunscreen",
    "sunblock": "sunscreen",
    "window cleaner": "glass-cleaner",
    "cologne": "perfume",
    "scent": "perfume",
    "bathbomb": "bath-bomb",
}

BUILDS: dict[str, LabData] = {
    "flashlight": {
        "name": "LED flashlight",
        "parts": (
            ("aa", 3),
            ("led-white", 3),
            ("resistor", 3),
            ("switch", 1),
            ("case", 1),
        ),
        "series": True,
        "steps": (
            "Put the three AA cells in series (4.5 V).",
            "Wire each LED with its own resistor.",
            "Put the switch in the positive line.",
        ),
    },
    "desk-fan": {
        "name": "USB desk fan",
        "parts": (("usb", 1), ("fan", 1), ("switch", 1), ("case", 1)),
        "series": True,
        "steps": ("USB 5 V to the fan through the switch.",),
    },
    "power-bank": {
        "name": "Power bank",
        "parts": (("18650", 2), ("tp4056", 1), ("boost-5v", 1), ("case", 1)),
        "series": False,
        "steps": (
            "Two 18650 cells side by side (same charge level!).",
            "TP4056 charges them from USB.",
            "The boost converter gives 5 V out.",
        ),
    },
    "weather-station": {
        "name": "Wi-Fi weather station",
        "parts": (
            ("usb", 1),
            ("regulator-3v3", 1),
            ("esp32", 1),
            ("temp-sensor", 1),
            ("oled", 1),
            ("case", 1),
        ),
        "series": True,
        "steps": (
            "ESP32 reads the DHT22 every minute.",
            "Shows it on the OLED and posts it over Wi-Fi.",
        ),
    },
    "robot-car": {
        "name": "Obstacle-avoiding robot car",
        "parts": (
            ("aa-nimh", 4),
            ("switch", 1),
            ("arduino", 1),
            ("motor-driver", 1),
            ("wheels", 1),
            ("distance-sensor", 1),
            ("chassis", 1),
        ),
        "series": True,
        "steps": (
            "Four NiMH cells in series (4.8 V).",
            "Arduino reads the distance sensor.",
            "Motor driver turns the wheels away from walls.",
        ),
    },
    "doorbell": {
        "name": "Doorbell",
        "parts": (("aa", 3), ("button", 1), ("buzzer", 1)),
        "series": True,
        "steps": ("Button in series with the buzzer.",),
    },
    "plant-waterer": {
        "name": "Automatic plant waterer",
        "parts": (
            ("usb", 1),
            ("arduino", 1),
            ("soil-sensor", 1),
            ("relay", 1),
            ("pump", 1),
        ),
        "series": True,
        "steps": (
            "Arduino checks soil moisture.",
            "When dry, the relay runs the pump for 3 seconds.",
        ),
    },
    "night-light": {
        "name": "Automatic night light",
        "parts": (
            ("usb", 1),
            ("arduino", 1),
            ("light-sensor", 1),
            ("led-white", 4),
            ("resistor", 4),
            ("transistor", 1),
        ),
        "series": True,
        "steps": (
            "The light sensor tells the Arduino when it's dark.",
            "A transistor switches the LEDs on.",
        ),
    },
    "solar-charger": {
        "name": "Solar phone charger",
        "parts": (
            ("solar", 1),
            ("tp4056", 1),
            ("18650", 1),
            ("boost-5v", 1),
            ("case", 1),
        ),
        "series": True,
        "steps": (
            "Solar panel charges the cell through the TP4056.",
            "The boost converter gives 5 V USB.",
        ),
    },
}

BUILD_ALIASES = {
    "torch": "flashlight",
    "fan": "desk-fan",
    "powerbank": "power-bank",
    "battery pack": "power-bank",
    "weather": "weather-station",
    "robot": "robot-car",
    "car": "robot-car",
    "bell": "doorbell",
    "plant": "plant-waterer",
    "waterer": "plant-waterer",
    "lamp": "night-light",
    "solar": "solar-charger",
}


def _key(text: str, table: dict[str, LabData], aliases: dict[str, str]) -> str | None:
    wanted = re.sub(r"[^a-z0-9 ]+", " ", text.lower()).strip()
    wanted = re.sub(
        r"\b(a|an|some|me|my|the|make|build|homemade|home made|diy)\b", " ", wanted
    )
    wanted = re.sub(r"\s+", " ", wanted).strip()
    slug = wanted.replace(" ", "-")
    if slug in table:
        return slug
    for alias, key in sorted(aliases.items(), key=lambda pair: -len(pair[0])):
        if re.search(rf"\b{re.escape(alias)}\b", wanted):
            return key
    for key, entry in table.items():
        if key.replace("-", " ") in wanted or str(entry["name"]).lower() in wanted:
            return key
    return None


def product_key(text: str) -> str | None:
    return _key(text, PRODUCTS, ALIASES)


def build_key(text: str) -> str | None:
    return _key(text, BUILDS, BUILD_ALIASES)


def _formula_for(chemical: Chemical) -> str:
    return (
        chemical.formula
        if chemical.formula and "n" not in chemical.formula
        else TYPICAL.get(chemical.id, "")
    )


# How much of a stock solution with no set strength is the chemical itself.
ACTIVE = {"sorbitol": 0.7, "sles": 0.27, "capb": 0.3, "decyl-glucoside": 0.5}


def _share(chemical: Chemical) -> float:
    """The mass fraction of a shelf item that is the chemical (the rest water)."""
    if chemical.state != "solution":
        return 1.0
    if chemical.concentration and chemical.molar_mass:
        return min(
            1.0, chemical.concentration * chemical.molar_mass / 1000 / chemical.density
        )
    return ACTIVE.get(chemical.id, 0.3)


def element_breakdown(parts: list[tuple[Chemical, float]]) -> list[LabData]:
    """Mass of each element across ingredients given in grams."""
    grams: defaultdict[str, float] = defaultdict(float)
    for chemical, amount in parts:
        formula = _formula_for(chemical)
        if not formula or amount <= 0:
            continue
        share = _share(chemical)
        for piece, mass in ((formula, amount * share), ("H2O", amount * (1 - share))):
            if mass <= 0:
                continue
            try:
                counts = parse(piece)
            except FormulaError:
                continue
            total = sum(
                BY_SYMBOL[symbol].mass * count for symbol, count in counts.items()
            )
            for symbol, count in counts.items():
                grams[symbol] += mass * BY_SYMBOL[symbol].mass * count / total
    whole = sum(grams.values()) or 1.0
    return [
        {
            "symbol": symbol,
            "name": BY_SYMBOL[symbol].name,
            "grams": round(amount, 3),
            "percent": round(100 * amount / whole, 3),
            "category": BY_SYMBOL[symbol].category,
        }
        for symbol, amount in sorted(grams.items(), key=lambda pair: -pair[1])
    ]


def build_product(
    name: str,
    ingredients: list[LabData],
    *,
    batch_g: float = 250,
    container: str = "bottle",
    steps: tuple[str, ...] | list[str] = (),
    ph: str = "",
    safety: str = "",
    source: str = "template",
) -> LabData:
    """Lay out a product: grams, colours, molecules, and elements."""
    rows: list[LabData] = []
    unknown: list[str] = []
    fixed = 0.0
    for entry in ingredients:
        chemical = resolve(str(entry.get("id") or entry.get("name") or ""))
        if chemical is None:
            unknown.append(str(entry.get("id") or entry.get("name")))
            continue
        percent = entry.get("percent")
        share = float(percent) if isinstance(percent, int | float) else None
        if share is not None:
            fixed += share
        rows.append(
            {
                "chemical": chemical,
                "percent": share,
                "purpose": str(entry.get("purpose") or ""),
            }
        )
    remainder = max(0.0, 100.0 - fixed)
    open_rows = [row for row in rows if row["percent"] is None]
    for row in open_rows:
        row["percent"] = remainder / len(open_rows)
    total = sum(float(str(row["percent"])) for row in rows) or 1.0
    out: list[LabData] = []
    parts: list[tuple[Chemical, float]] = []
    for row in rows:
        chemical = row["chemical"]
        assert isinstance(chemical, Chemical)
        percent = float(str(row["percent"])) * 100 / total
        grams = batch_g * percent / 100
        parts.append((chemical, grams))
        formula = _formula_for(chemical)
        out.append(
            {
                "id": chemical.id,
                "name": chemical.name,
                "formula": chemical.formula,
                "typical_formula": "" if chemical.formula else formula,
                "percent": round(percent, 3),
                "grams": round(grams, 3),
                "purpose": row["purpose"],
                "colour": chemical.colour,
                "kind": chemical.kind,
                "hazards": list(chemical.hazards),
                "elements": element_breakdown([(chemical, 100.0)]),
            }
        )
    out.sort(key=lambda row: -float(str(row["percent"])))
    visible = [
        (
            str(row["colour"]),
            float(str(row["percent"]))
            * (
                40
                if row["kind"] == "mixture" and "colour" in str(row["purpose"]).lower()
                else 1
            ),
        )
        for row in out
        if row["id"] != "water"
    ]
    colour, _ = blend(visible) if visible else ("#e3f2ff", 0.1)
    hazards = sorted({code for row in out for code in row["hazards"]})
    return {
        "name": name,
        "container": container,
        "batch_g": batch_g,
        "colour": colour,
        "ph": ph,
        "ingredients": out,
        "elements": element_breakdown(parts),
        "steps": list(steps),
        "safety": safety,
        "hazards": hazards,
        "unknown": unknown,
        "source": source,
    }


def template_product(key: str, *, batch_g: float | None = None) -> LabData:
    entry = PRODUCTS[key]
    ingredients = entry["ingredients"]
    assert isinstance(ingredients, tuple)
    product = build_product(
        str(entry["name"]),
        [{"id": i, "percent": p, "purpose": why} for i, p, why in ingredients],
        batch_g=float(batch_g or float(str(entry["batch_g"]))),
        container=str(entry["container"]),
        steps=tuple(entry.get("steps", ())),
        ph=str(entry.get("ph", "")),
        safety=str(entry.get("safety", "")),
    )
    product["template"] = key
    product["reaction"] = list(entry.get("reaction", ()))
    return product


def catalogue() -> LabData:
    return {
        "products": [
            {"key": key, "name": entry["name"], "container": entry["container"]}
            for key, entry in PRODUCTS.items()
        ],
        "builds": [
            {"key": key, "name": entry["name"]} for key, entry in BUILDS.items()
        ],
    }
