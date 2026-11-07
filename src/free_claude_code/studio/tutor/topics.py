"""The maths an electrician uses, as practice questions with worked answers.

Topics follow the path to an electrician's licence in NSW: the maths in
apprenticeship entry (aptitude) tests, transposing formulas, DC circuits
(first year of the Certificate III), AC (second year), three-phase and
machines (third year), and the installation calculations met in the final
licensing assessment. Every question is made from a template with random
values and solved here in code, step by step, so the answer and the
working are always right (a model never makes up the numbers).

Values that come from Australian Standards tables (cable voltage drop in
mV/A·m, for example) are given in the question, never quoted from the
tables: look them up in AS/NZS 3008 on the job.
"""

import math
import random
from collections.abc import Callable
from dataclasses import dataclass

SQRT3 = math.sqrt(3)


@dataclass(frozen=True, slots=True)
class Question:
    id: str
    topic: str
    prompt: str
    answer: float
    unit: str
    places: int
    """Decimal places the answer is shown to (and is accepted at)."""
    steps: tuple[str, ...]
    hint: str
    tolerance: float = 0.01
    """Relative tolerance (1%) on top of rounding to ``places``."""

    def accepts(self, value: float) -> bool:
        slack = max(abs(self.answer) * self.tolerance, 0.5 * 10**-self.places)
        return abs(value - self.answer) <= slack + 1e-12

    def shown(self) -> str:
        if self.unit == "$":
            return f"${self.answer:,.2f}"
        return f"{fmt(self.answer, self.places)}{f' {self.unit}' if self.unit else ''}"


@dataclass(frozen=True, slots=True)
class Topic:
    id: str
    stage: str
    title: str
    why: str
    lesson: str
    formulas: tuple[str, ...]
    make: Callable[[random.Random], tuple[str, float, str, int, tuple[str, ...], str]]
    """(prompt, answer, unit, places, steps, hint)"""


STAGES: tuple[tuple[str, str], ...] = (
    ("entry", "Entry test maths"),
    ("algebra", "Formulas and algebra"),
    ("dc", "DC circuits (year 1)"),
    ("ac", "AC theory (year 2)"),
    ("three", "Three-phase and machines (year 3)"),
    ("install", "Installation calculations (licence assessment)"),
)


def fmt(value: float, places: int) -> str:
    text = f"{value:,.{places}f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def _pick(rng: random.Random, *values: float) -> float:
    return rng.choice(values)


# ------------------------------------------------------------ entry test maths


def _order(rng: random.Random):
    a, b, c, d, e = (rng.randint(2, 12) for _ in range(5))
    d = d * e  # so the division comes out whole
    answer = a + b * c - d / e
    return (
        f"Work out {a} + {b} × {c} − {d} ÷ {e}.",
        answer,
        "",
        2,
        (
            "Multiply and divide before adding and subtracting.",
            f"{b} × {c} = {b * c} and {d} ÷ {e} = {fmt(d / e, 2)}.",
            f"{a} + {b * c} − {fmt(d / e, 2)} = {fmt(answer, 2)}.",
        ),
        "Multiplication and division come first.",
    )


def _fractions(rng: random.Random):
    a, c = rng.randint(1, 5), rng.randint(1, 5)
    b, d = rng.choice((2, 3, 4, 5, 8)), rng.choice((3, 4, 6, 8, 10))
    a, c = min(a, b - 1) or 1, min(c, d - 1) or 1
    common = b * d // math.gcd(b, d)
    top = a * (common // b) + c * (common // d)
    answer = top / common
    return (
        f"Add {a}/{b} + {c}/{d}. Give a decimal (or a fraction like 7/8).",
        answer,
        "",
        3,
        (
            f"Find a common denominator: {common}.",
            f"{a}/{b} = {a * (common // b)}/{common} and {c}/{d} = {c * (common // d)}/{common}.",
            f"Add the tops: {top}/{common} = {fmt(answer, 3)}.",
        ),
        "Make the bottoms the same before adding the tops.",
    )


def _percent(rng: random.Random):
    if rng.random() < 0.5:
        price = rng.randint(1200, 9900) / 100
        answer = price * 1.10
        return (
            f"A circuit breaker costs ${fmt(price, 2)} before GST. GST is 10%. "
            "What is the price with GST, in dollars?",
            answer,
            "$",
            2,
            (
                f"10% of {fmt(price, 2)} is {fmt(price * 0.1, 2)}.",
                f"{fmt(price, 2)} + {fmt(price * 0.1, 2)} = {fmt(answer, 2)}.",
                "Or in one step: price × 1.10.",
            ),
            "Adding 10% is the same as multiplying by 1.10.",
        )
    drum = rng.choice((100, 150, 200, 250, 500))
    used = rng.randint(5, 60)
    answer = drum * (1 - used / 100)
    return (
        f"A cable drum holds {drum} m. You use {used}% of it. How many metres are left?",
        answer,
        "m",
        1,
        (
            f"{used}% of {drum} m is {fmt(drum * used / 100, 1)} m.",
            f"{drum} − {fmt(drum * used / 100, 1)} = {fmt(answer, 1)} m left.",
        ),
        "Find the part used, then take it away (or keep 100% − used%).",
    )


_PREFIXES = (
    ("kV", "V", 1000.0),
    ("mA", "A", 0.001),
    ("kW", "W", 1000.0),
    ("kΩ", "Ω", 1000.0),
    ("MΩ", "kΩ", 1000.0),
    ("µF", "nF", 1000.0),
    ("mm²", "m²", 1e-6),
)


def _units(rng: random.Random):
    have, want, factor = rng.choice(_PREFIXES)
    if rng.random() < 0.5:
        have, want, factor = want, have, 1 / factor
    value = rng.choice((0.047, 0.33, 1.5, 2.5, 4.7, 15, 33, 220, 450, 2200))
    answer = value * factor
    places = 9 if abs(answer) < 0.01 else 4
    return (
        f"Convert {fmt(value, 4)} {have} to {want}.",
        answer,
        want,
        places,
        (
            f"1 {have} = {fmt(factor, 9)} {want}.",
            f"{fmt(value, 4)} × {fmt(factor, 9)} = {fmt(answer, places)} {want}.",
        ),
        "k is a thousand, M a million, m a thousandth, µ a millionth, n a billionth.",
    )


def _area(rng: random.Random):
    if rng.random() < 0.5:
        d = rng.choice((1.13, 1.38, 1.78, 2.26, 2.76, 3.57))
        answer = math.pi * d**2 / 4
        return (
            f"A round copper core is {d} mm across. What is its cross-sectional "
            "area in mm²?",
            answer,
            "mm²",
            2,
            (
                "Area of a circle = π × d² ÷ 4 (or π × r²).",
                f"π × {d}² ÷ 4 = π × {fmt(d**2, 4)} ÷ 4 = {fmt(answer, 2)} mm².",
            ),
            "Square the diameter first, then multiply by π and divide by 4.",
        )
    w, h = rng.randint(28, 65) / 10, rng.randint(25, 50) / 10
    answer = w * h
    return (
        f"A room is {w} m by {h} m. What is its floor area in m²?",
        answer,
        "m²",
        2,
        ("Area = length × width.", f"{w} × {h} = {fmt(answer, 2)} m²."),
        "Multiply the two sides.",
    )


# ------------------------------------------------------------ algebra


def _transpose(rng: random.Random):
    kind = rng.choice(("R", "V", "I"))
    if kind == "R":
        p = rng.choice((1000, 1500, 2000, 2400, 3000))
        v = 230
        answer = v**2 / p
        return (
            f"Using P = V² ÷ R, find R when P = {p} W and V = {v} V.",
            answer,
            "Ω",
            2,
            (
                "Make R the subject: multiply both sides by R, then divide by P: R = V² ÷ P.",
                f"R = {v}² ÷ {p} = {v**2} ÷ {p} = {fmt(answer, 2)} Ω.",
            ),
            "Swap R and P: R = V² ÷ P.",
        )
    if kind == "V":
        p = rng.choice((500, 1000, 2000, 2300))
        r = rng.choice((26.45, 52.9, 105.8))
        answer = math.sqrt(p * r)
        return (
            f"Using P = V² ÷ R, find V when P = {p} W and R = {r} Ω.",
            answer,
            "V",
            1,
            (
                "Multiply both sides by R: V² = P × R; then take the square root: V = √(P × R).",
                f"V = √({p} × {r}) = √{fmt(p * r, 1)} = {fmt(answer, 1)} V.",
            ),
            "Get V² on its own first, then square-root both sides.",
        )
    p = rng.choice((60, 100, 460, 920, 1150))
    r = rng.choice((10, 20, 47, 100))
    answer = math.sqrt(p / r)
    return (
        f"Using P = I² × R, find I when P = {p} W and R = {r} Ω.",
        answer,
        "A",
        2,
        (
            "Divide both sides by R: I² = P ÷ R; then square-root: I = √(P ÷ R).",
            f"I = √({p} ÷ {r}) = √{fmt(p / r, 3)} = {fmt(answer, 2)} A.",
        ),
        "Undo the × R first, then the square.",
    )


def _equation(rng: random.Random):
    x = rng.randint(2, 15)
    a, b = rng.randint(2, 9), rng.randint(1, 30)
    c = a * x + b
    return (
        f"Solve for x: {a}x + {b} = {c}.",
        float(x),
        "",
        2,
        (
            f"Take {b} from both sides: {a}x = {c - b}.",
            f"Divide both sides by {a}: x = {c - b} ÷ {a} = {x}.",
        ),
        "Undo the + first, then the ×.",
    )


# ------------------------------------------------------------ DC circuits


def _ohms(rng: random.Random):
    kind = rng.choice(("I", "V", "R"))
    r = rng.choice((4.7, 10, 22, 47, 100, 220, 470))
    i = rng.choice((0.05, 0.2, 0.5, 1.5, 2, 4.6, 10))
    if kind == "I":
        v = rng.choice((12, 24, 48, 230))
        answer = v / r
        return (
            f"A {r} Ω element is connected to {v} V. What current flows (A)?",
            answer,
            "A",
            3,
            ("Ohm's law: I = V ÷ R.", f"I = {v} ÷ {r} = {fmt(answer, 3)} A."),
            "Current = voltage ÷ resistance.",
        )
    if kind == "V":
        answer = i * r
        return (
            f"{i} A flows through a {r} Ω resistor. What voltage is across it?",
            answer,
            "V",
            2,
            ("Ohm's law: V = I × R.", f"V = {i} × {r} = {fmt(answer, 2)} V."),
            "Voltage = current × resistance.",
        )
    v = rng.choice((12, 24, 230))
    answer = v / i
    return (
        f"A load draws {i} A from {v} V. What is its resistance?",
        answer,
        "Ω",
        2,
        ("Ohm's law: R = V ÷ I.", f"R = {v} ÷ {i} = {fmt(answer, 2)} Ω."),
        "Resistance = voltage ÷ current.",
    )


def _power(rng: random.Random):
    kind = rng.choice(("VI", "I2R", "current"))
    if kind == "VI":
        v, i = 230, rng.choice((2.5, 4.3, 8.7, 10, 13))
        answer = v * i
        return (
            f"An appliance draws {i} A at {v} V. What is its power in watts?",
            answer,
            "W",
            1,
            ("P = V × I.", f"P = {v} × {i} = {fmt(answer, 1)} W."),
            "Power = voltage × current.",
        )
    if kind == "I2R":
        i, r = rng.choice((2, 5, 10, 16)), rng.choice((0.1, 0.25, 0.5, 1.2))
        answer = i**2 * r
        return (
            f"{i} A flows through a cable with {r} Ω resistance. How much power "
            "is lost as heat (W)?",
            answer,
            "W",
            2,
            ("P = I² × R.", f"P = {i}² × {r} = {i**2} × {r} = {fmt(answer, 2)} W."),
            "Square the current, then multiply by the resistance.",
        )
    p = rng.choice((1000, 1800, 2400, 3600))
    answer = p / 230
    return (
        f"A {p} W heater runs on 230 V. What current does it draw (A)?",
        answer,
        "A",
        2,
        ("I = P ÷ V.", f"I = {p} ÷ 230 = {fmt(answer, 2)} A."),
        "Current = power ÷ voltage.",
    )


def _energy(rng: random.Random):
    kw = rng.choice((0.8, 1.2, 2.0, 2.4, 3.6))
    hours = rng.choice((1.5, 2, 3.5, 4, 6))
    days = rng.choice((7, 30, 90))
    cents = rng.choice((28, 30, 32, 35))
    kwh = kw * hours * days
    answer = kwh * cents / 100
    return (
        f"A {kw} kW heater runs {hours} h a day for {days} days. Power costs "
        f"{cents} c per kWh. What does it cost, in dollars?",
        answer,
        "$",
        2,
        (
            "Energy (kWh) = power (kW) × hours.",
            f"{kw} × {hours} × {days} = {fmt(kwh, 2)} kWh.",
            f"Cost = {fmt(kwh, 2)} × ${cents / 100:.2f} = ${fmt(answer, 2)}.",
        ),
        "Work out the kWh first, then multiply by the price per kWh.",
    )


def _series(rng: random.Random):
    rs = [rng.choice((10, 22, 33, 47, 68, 100)) for _ in range(3)]
    v = rng.choice((12, 24, 48))
    total = sum(rs)
    answer = v / total
    return (
        f"Resistors of {rs[0]} Ω, {rs[1]} Ω and {rs[2]} Ω are in series across "
        f"{v} V. What current flows (A)?",
        answer,
        "A",
        4,
        (
            "In series the resistances add: R = R1 + R2 + R3.",
            f"R = {rs[0]} + {rs[1]} + {rs[2]} = {total} Ω.",
            f"I = V ÷ R = {v} ÷ {total} = {fmt(answer, 4)} A.",
        ),
        "Add the resistors first, then use Ohm's law.",
    )


def _parallel(rng: random.Random):
    count = rng.choice((2, 3))
    rs = [rng.choice((10, 20, 40, 60, 100, 120)) for _ in range(count)]
    answer = 1 / sum(1 / r for r in rs)
    shown = " + ".join(f"1/{r}" for r in rs)
    return (
        f"What is the total resistance of {', '.join(f'{r} Ω' for r in rs)} in "
        "parallel?",
        answer,
        "Ω",
        2,
        (
            "In parallel: 1/R = 1/R1 + 1/R2 (+ 1/R3).",
            f"1/R = {shown} = {fmt(sum(1 / r for r in rs), 5)}.",
            f"R = 1 ÷ {fmt(sum(1 / r for r in rs), 5)} = {fmt(answer, 2)} Ω.",
            "Check: the total is always less than the smallest resistor.",
        ),
        "Add the reciprocals, then take the reciprocal of the sum.",
    )


def _divider(rng: random.Random):
    r1, r2 = (
        rng.choice((1000, 2200, 4700, 10000)),
        rng.choice((1000, 3300, 4700, 10000)),
    )
    v = rng.choice((5, 9, 12, 24))
    answer = v * r2 / (r1 + r2)
    return (
        f"A voltage divider has R1 = {r1} Ω (top) and R2 = {r2} Ω (bottom) across "
        f"{v} V. What is the voltage across R2?",
        answer,
        "V",
        3,
        (
            "V2 = V × R2 ÷ (R1 + R2).",
            f"V2 = {v} × {r2} ÷ ({r1} + {r2}) = {fmt(answer, 3)} V.",
        ),
        "The voltage splits in proportion to the resistances.",
    )


def _resistivity(rng: random.Random):
    length = rng.choice((10, 25, 40, 60, 100))
    area = rng.choice((1.0, 1.5, 2.5, 4.0, 6.0))
    rho = 1.72e-8
    answer = rho * length / (area * 1e-6)
    return (
        f"Copper has a resistivity of 1.72 × 10⁻⁸ Ω·m. What is the resistance "
        f"of {length} m of {area} mm² copper conductor (Ω)?",
        answer,
        "Ω",
        4,
        (
            "R = ρ × L ÷ A, with A in m² (1 mm² = 1 × 10⁻⁶ m²).",
            f"A = {area} × 10⁻⁶ m².",
            f"R = 1.72 × 10⁻⁸ × {length} ÷ ({area} × 10⁻⁶) = {fmt(answer, 4)} Ω.",
        ),
        "Convert mm² to m² before dividing.",
    )


def _temperature(rng: random.Random):
    r20 = rng.choice((10, 25, 50, 100))
    t = rng.choice((45, 60, 75, 90))
    alpha = 0.00393
    answer = r20 * (1 + alpha * (t - 20))
    return (
        f"A copper winding measures {r20} Ω at 20 °C. Copper's temperature "
        f"coefficient is 0.00393 per °C. What is its resistance at {t} °C?",
        answer,
        "Ω",
        2,
        (
            "R₂ = R₁ × (1 + α × (T₂ − T₁)).",
            f"R₂ = {r20} × (1 + 0.00393 × ({t} − 20)) = {r20} × "
            f"{fmt(1 + alpha * (t - 20), 5)} = {fmt(answer, 2)} Ω.",
        ),
        "Copper's resistance rises as it heats up.",
    )


def _efficiency(rng: random.Random):
    pin = rng.choice((1000, 1500, 2200, 4000))
    eff = rng.choice((0.72, 0.8, 0.85, 0.9))
    pout = round(pin * eff)
    answer = pout / pin * 100
    return (
        f"A motor takes {pin} W in and gives {pout} W of mechanical power out. "
        "What is its efficiency (%)?",
        answer,
        "%",
        1,
        (
            "Efficiency = output ÷ input × 100.",
            f"{pout} ÷ {pin} × 100 = {fmt(answer, 1)}%.",
        ),
        "Output over input, as a percentage.",
    )


# ------------------------------------------------------------ AC


def _rms(rng: random.Random):
    if rng.random() < 0.5:
        v = rng.choice((230, 240, 400, 12))
        answer = v * math.sqrt(2)
        return (
            f"A sine wave has an RMS voltage of {v} V. What is its peak voltage?",
            answer,
            "V",
            1,
            ("Peak = RMS × √2 (about 1.414).", f"{v} × 1.414 = {fmt(answer, 1)} V."),
            "The peak is about 1.414 times the RMS value.",
        )
    f = rng.choice((50, 60, 400))
    answer = 1000 / f
    return (
        f"What is the period of a {f} Hz supply, in milliseconds?",
        answer,
        "ms",
        2,
        ("T = 1 ÷ f.", f"T = 1 ÷ {f} = {fmt(1 / f, 5)} s = {fmt(answer, 2)} ms."),
        "Period is one over frequency; 1 s = 1000 ms.",
    )


def _reactance(rng: random.Random):
    f = 50
    if rng.random() < 0.5:
        henry = rng.choice((0.05, 0.1, 0.2, 0.318))
        answer = 2 * math.pi * f * henry
        return (
            f"What is the reactance of a {henry} H inductor at {f} Hz (Ω)?",
            answer,
            "Ω",
            2,
            ("X_L = 2πfL.", f"X_L = 2 × π × {f} × {henry} = {fmt(answer, 2)} Ω."),
            "Inductive reactance grows with frequency.",
        )
    micro = rng.choice((10, 22, 47, 100))
    answer = 1 / (2 * math.pi * f * micro * 1e-6)
    return (
        f"What is the reactance of a {micro} µF capacitor at {f} Hz (Ω)?",
        answer,
        "Ω",
        2,
        (
            "X_C = 1 ÷ (2πfC), with C in farads (1 µF = 10⁻⁶ F).",
            f"X_C = 1 ÷ (2 × π × {f} × {micro} × 10⁻⁶) = {fmt(answer, 2)} Ω.",
        ),
        "Capacitive reactance falls as frequency rises.",
    )


def _impedance(rng: random.Random):
    r = rng.choice((20, 30, 40, 60))
    x = rng.choice((15, 30, 40, 80))
    z = math.hypot(r, x)
    answer = 230 / z
    return (
        f"A coil has {r} Ω resistance and {x} Ω inductive reactance on 230 V. "
        "What current flows (A)?",
        answer,
        "A",
        3,
        (
            "Impedance Z = √(R² + X_L²) (the impedance triangle).",
            f"Z = √({r}² + {x}²) = {fmt(z, 3)} Ω.",
            f"I = V ÷ Z = 230 ÷ {fmt(z, 3)} = {fmt(answer, 3)} A.",
        ),
        "Use Pythagoras on R and X, not R + X.",
    )


def _power_factor(rng: random.Random):
    i = rng.choice((5, 8, 10, 12))
    pf = rng.choice((0.7, 0.75, 0.8, 0.85, 0.9))
    s = 230 * i
    p = s * pf
    answer = p
    return (
        f"A load draws {i} A at 230 V with a power factor of {pf}. What is its "
        "true power (W)?",
        answer,
        "W",
        1,
        (
            "Apparent power S = V × I (VA); true power P = S × power factor.",
            f"S = 230 × {i} = {s} VA.",
            f"P = {s} × {pf} = {fmt(answer, 1)} W.",
        ),
        "True power is apparent power times the power factor.",
    )


def _correction(rng: random.Random):
    p = rng.choice((10, 20, 30, 50))
    pf1 = rng.choice((0.7, 0.75, 0.8))
    pf2 = rng.choice((0.9, 0.95))
    t1 = math.tan(math.acos(pf1))
    t2 = math.tan(math.acos(pf2))
    answer = p * (t1 - t2)
    return (
        f"A {p} kW load runs at power factor {pf1}. What capacitor size (kVAr) "
        f"raises it to {pf2}?",
        answer,
        "kVAr",
        2,
        (
            "Q_C = P × (tan θ₁ − tan θ₂), where θ = cos⁻¹(power factor).",
            f"θ₁ = cos⁻¹({pf1}) → tan θ₁ = {fmt(t1, 4)}; θ₂ = cos⁻¹({pf2}) → "
            f"tan θ₂ = {fmt(t2, 4)}.",
            f"Q_C = {p} × ({fmt(t1, 4)} − {fmt(t2, 4)}) = {fmt(answer, 2)} kVAr.",
        ),
        "Find each angle from cos⁻¹ of the power factor, then use tan.",
    )


# ------------------------------------------------------------ three-phase


def _star(rng: random.Random):
    if rng.random() < 0.5:
        vl = rng.choice((400, 415, 433))
        answer = vl / SQRT3
        return (
            f"A star-connected supply has a line voltage of {vl} V. What is the "
            "phase voltage?",
            answer,
            "V",
            1,
            ("In star, V_phase = V_line ÷ √3.", f"{vl} ÷ 1.732 = {fmt(answer, 1)} V."),
            "Line voltage is √3 (about 1.732) times phase voltage.",
        )
    iph = rng.choice((5, 10, 16, 20))
    answer = iph * SQRT3
    return (
        f"A delta-connected motor has {iph} A in each winding (phase current). "
        "What is the line current?",
        answer,
        "A",
        2,
        ("In delta, I_line = I_phase × √3.", f"{iph} × 1.732 = {fmt(answer, 2)} A."),
        "In delta the line current is √3 times the phase current.",
    )


def _three_power(rng: random.Random):
    il = rng.choice((10, 16, 25, 32))
    pf = rng.choice((0.8, 0.85, 0.9))
    answer = SQRT3 * 400 * il * pf / 1000
    return (
        f"A 400 V three-phase motor draws {il} A per line at power factor {pf}. "
        "What is its input power in kW?",
        answer,
        "kW",
        2,
        (
            "P = √3 × V_line × I_line × power factor.",
            f"P = 1.732 × 400 × {il} × {pf} = {fmt(answer * 1000, 0)} W = "
            f"{fmt(answer, 2)} kW.",
        ),
        "Don't forget the √3 for three-phase.",
    )


def _transformer(rng: random.Random):
    vp = rng.choice((230, 400))
    np_ = rng.choice((460, 800, 1000, 2000))
    ns = rng.choice((24, 40, 48, 120))
    answer = vp * ns / np_
    return (
        f"A transformer has {np_} turns on the primary and {ns} on the "
        f"secondary. The primary is on {vp} V. What is the secondary voltage?",
        answer,
        "V",
        2,
        (
            "V_s ÷ V_p = N_s ÷ N_p, so V_s = V_p × N_s ÷ N_p.",
            f"V_s = {vp} × {ns} ÷ {np_} = {fmt(answer, 2)} V.",
        ),
        "Voltage goes up or down with the turns ratio.",
    )


def _motor(rng: random.Random):
    poles = rng.choice((2, 4, 6, 8))
    ns = 120 * 50 / poles
    if rng.random() < 0.5:
        return (
            f"What is the synchronous speed of a {poles}-pole motor on 50 Hz (rpm)?",
            ns,
            "rpm",
            0,
            ("n_s = 120 × f ÷ p.", f"n_s = 120 × 50 ÷ {poles} = {fmt(ns, 0)} rpm."),
            "More poles, slower speed.",
        )
    n = ns * rng.choice((0.96, 0.95, 0.97))
    n = round(n)
    answer = (ns - n) / ns * 100
    return (
        f"A {poles}-pole 50 Hz induction motor runs at {n} rpm. What is its slip (%)?",
        answer,
        "%",
        2,
        (
            f"Synchronous speed n_s = 120 × 50 ÷ {poles} = {fmt(ns, 0)} rpm.",
            "Slip = (n_s − n) ÷ n_s × 100.",
            f"({fmt(ns, 0)} − {n}) ÷ {fmt(ns, 0)} × 100 = {fmt(answer, 2)}%.",
        ),
        "Work out the synchronous speed first.",
    )


# ------------------------------------------------------------ installation


def _voltage_drop(rng: random.Random):
    mv = rng.choice((9.48, 15.6, 24.7, 3.86))
    current = rng.choice((10, 16, 20, 25, 32))
    length = rng.choice((15, 25, 30, 40, 55))
    answer = mv * current * length / 1000
    return (
        f"A single-phase circuit carries {current} A over {length} m of cable "
        f"rated {mv} mV/A·m (from AS/NZS 3008). What is the voltage drop (V)? "
        "(The Wiring Rules allow 5% of 230 V, which is 11.5 V, in total.)",
        answer,
        "V",
        2,
        (
            "V_d = (mV/A·m × I × L) ÷ 1000.",
            f"V_d = {mv} × {current} × {length} ÷ 1000 = {fmt(answer, 2)} V.",
            f"That is {fmt(answer / 230 * 100, 2)}% of 230 V "
            + ("(within 5%)." if answer <= 11.5 else "(over 5%: use a bigger cable)."),
        ),
        "Multiply the three numbers, then divide by 1000 to turn mV into V.",
    )


def _max_length(rng: random.Random):
    mv = rng.choice((9.48, 15.6, 24.7))
    current = rng.choice((10, 16, 20))
    allowed = rng.choice((5.75, 7.0, 11.5))
    answer = allowed * 1000 / (mv * current)
    return (
        f"A circuit may drop {allowed} V. The cable is {mv} mV/A·m and carries "
        f"{current} A. What is the longest run allowed (m)?",
        answer,
        "m",
        1,
        (
            "From V_d = mV/A·m × I × L ÷ 1000: L = V_d × 1000 ÷ (mV/A·m × I).",
            f"L = {allowed} × 1000 ÷ ({mv} × {current}) = {fmt(answer, 1)} m.",
        ),
        "Transpose the voltage-drop formula for L.",
    )


def _fault_loop(rng: random.Random):
    rating = rng.choice((10, 16, 20, 25, 32))
    multiple = rng.choice((5, 7.5, 10))
    ia = rating * multiple
    answer = 230 / ia
    return (
        f"A {rating} A circuit breaker trips instantly at {multiple} × its "
        f"rating. What is the highest earth fault-loop impedance (Ω) that still "
        "trips it instantly on 230 V?",
        answer,
        "Ω",
        3,
        (
            f"The tripping current I_a = {rating} × {multiple} = {fmt(ia, 1)} A.",
            "Z_s = U₀ ÷ I_a, with U₀ = 230 V.",
            f"Z_s = 230 ÷ {fmt(ia, 1)} = {fmt(answer, 3)} Ω.",
        ),
        "The loop must let enough fault current flow to trip the breaker fast.",
    )


TOPICS: tuple[Topic, ...] = (
    Topic(
        "order",
        "entry",
        "Order of operations",
        "Entry tests start here, and every formula depends on doing steps in the right order.",
        "Brackets first, then powers, then multiply and divide (left to right), then add and subtract.",
        ("B, O, D/M, A/S",),
        _order,
    ),
    Topic(
        "fractions",
        "entry",
        "Fractions",
        "Measurements and ratios come as fractions on the tools and plans.",
        "To add fractions, give them the same bottom number, then add the tops.",
        ("a/b + c/d = (a×d + c×b) ÷ (b×d)",),
        _fractions,
    ),
    Topic(
        "percent",
        "entry",
        "Percentages and GST",
        "Quotes, GST, efficiency and voltage-drop limits are all percentages.",
        "Percent means per hundred: 18% of 250 is 0.18 × 250. Adding 10% GST is × 1.10.",
        ("part = whole × % ÷ 100", "with GST = price × 1.10"),
        _percent,
    ),
    Topic(
        "units",
        "entry",
        "Units and metric prefixes",
        "Meters and data sheets mix kV, mA, kΩ and µF: getting the prefix wrong is a 1000× mistake.",
        "k = ×1000, M = ×1,000,000, m = ÷1000, µ = ÷1,000,000, n = ÷1,000,000,000.",
        ("1 kΩ = 1000 Ω", "1 mA = 0.001 A", "1 µF = 1000 nF"),
        _units,
    ),
    Topic(
        "area",
        "entry",
        "Areas",
        "Cable sizes are cross-sectional areas in mm²; rooms and switchboards need areas too.",
        "Rectangle: length × width. Circle: π × d² ÷ 4.",
        ("A = l × w", "A = π d² ÷ 4"),
        _area,
    ),
    Topic(
        "transpose",
        "algebra",
        "Transposing formulas",
        "Every electrical formula has to be rearranged for the value you're after.",
        "Do the same thing to both sides until the unknown is on its own: undo + and − first, then × and ÷, then powers.",
        ("P = V²/R → R = V²/P", "P = I²R → I = √(P/R)"),
        _transpose,
    ),
    Topic(
        "equations",
        "algebra",
        "Solving equations",
        "The same skill as transposing, with numbers.",
        "Undo what's been done to x, in reverse order.",
        ("ax + b = c → x = (c − b) ÷ a",),
        _equation,
    ),
    Topic(
        "ohms",
        "dc",
        "Ohm's law",
        "The first law of the trade: voltage, current and resistance.",
        "V = I × R. Cover the one you want: V = IR, I = V/R, R = V/I.",
        ("V = I R", "I = V / R", "R = V / I"),
        _ohms,
    ),
    Topic(
        "power",
        "dc",
        "Power",
        "Sizing circuits and protection starts from the load's power.",
        "P = V × I; with Ohm's law also P = I²R and P = V²/R.",
        ("P = V I", "P = I² R", "P = V² / R"),
        _power,
    ),
    Topic(
        "energy",
        "dc",
        "Energy and cost",
        "Customers ask what an appliance costs to run.",
        "Energy (kWh) = power (kW) × time (h); cost = kWh × price per kWh.",
        ("E = P × t", "cost = kWh × rate"),
        _energy,
    ),
    Topic(
        "series",
        "dc",
        "Series circuits",
        "Strings of loads and cable resistance in a run add in series.",
        "In series the current is the same everywhere and the resistances add.",
        ("R = R1 + R2 + R3",),
        _series,
    ),
    Topic(
        "parallel",
        "dc",
        "Parallel circuits",
        "Everything on a household circuit is wired in parallel.",
        "In parallel the voltage is the same across each branch; 1/R = 1/R1 + 1/R2 + …",
        ("1/R = 1/R1 + 1/R2", "two only: R = R1R2 ÷ (R1 + R2)"),
        _parallel,
    ),
    Topic(
        "divider",
        "dc",
        "Voltage dividers",
        "Sensors and control circuits use dividers.",
        "The supply splits in proportion to the resistances.",
        ("V2 = V × R2 ÷ (R1 + R2)",),
        _divider,
    ),
    Topic(
        "resistivity",
        "dc",
        "Conductor resistance",
        "Long runs and thin cables add resistance (and voltage drop).",
        "R = ρL/A: longer is more resistance, thicker is less. Convert mm² to m².",
        ("R = ρ L / A",),
        _resistivity,
    ),
    Topic(
        "temperature",
        "dc",
        "Resistance and temperature",
        "Windings and cables run warmer under load, and their resistance rises.",
        "R₂ = R₁(1 + α(T₂ − T₁)); copper's α is about 0.00393 per °C from 20 °C.",
        ("R₂ = R₁ (1 + α ΔT)",),
        _temperature,
    ),
    Topic(
        "efficiency",
        "dc",
        "Efficiency",
        "Motors and transformers lose some power as heat.",
        "Efficiency = output ÷ input × 100%.",
        ("η = P_out / P_in × 100",),
        _efficiency,
    ),
    Topic(
        "rms",
        "ac",
        "RMS, peak and period",
        "230 V is an RMS value: insulation must handle the peak.",
        "Peak = RMS × √2; period T = 1/f (50 Hz is 20 ms).",
        ("V_peak = V_rms × √2", "T = 1 / f"),
        _rms,
    ),
    Topic(
        "reactance",
        "ac",
        "Reactance",
        "Coils and capacitors oppose AC differently from resistors.",
        "X_L = 2πfL rises with frequency; X_C = 1/(2πfC) falls with it.",
        ("X_L = 2π f L", "X_C = 1 / (2π f C)"),
        _reactance,
    ),
    Topic(
        "impedance",
        "ac",
        "Impedance",
        "Motors and fluorescent fittings are resistance and reactance together.",
        "Add R and X with Pythagoras: Z = √(R² + X²); then I = V/Z.",
        ("Z = √(R² + X²)", "I = V / Z"),
        _impedance,
    ),
    Topic(
        "pf",
        "ac",
        "Power factor",
        "Inductive loads draw more current than their power suggests.",
        "Apparent power S = VI (VA); true power P = S × pf (W).",
        ("S = V I", "P = S × pf", "Q = √(S² − P²)"),
        _power_factor,
    ),
    Topic(
        "correction",
        "ac",
        "Power factor correction",
        "Capacitors are fitted to cut the current a site draws.",
        "Q_C = P(tan θ₁ − tan θ₂), with θ = cos⁻¹(pf).",
        ("Q_C = P (tan θ₁ − tan θ₂)",),
        _correction,
    ),
    Topic(
        "star",
        "three",
        "Star and delta",
        "Three-phase supplies and motors are connected in star or delta.",
        "Star: V_line = √3 V_phase, I_line = I_phase. Delta: V_line = V_phase, I_line = √3 I_phase.",
        ("V_L = √3 V_ph (star)", "I_L = √3 I_ph (delta)"),
        _star,
    ),
    Topic(
        "three_power",
        "three",
        "Three-phase power",
        "Sizing motors, cables and protection on three-phase.",
        "P = √3 × V_L × I_L × pf.",
        ("P = √3 V_L I_L pf",),
        _three_power,
    ),
    Topic(
        "transformer",
        "three",
        "Transformers",
        "Control transformers, isolation transformers, step-down supplies.",
        "Voltage follows the turns ratio: V_s/V_p = N_s/N_p; current goes the other way.",
        ("V_s = V_p × N_s / N_p",),
        _transformer,
    ),
    Topic(
        "motor",
        "three",
        "Motor speed and slip",
        "Picking and fault-finding induction motors.",
        "Synchronous speed n_s = 120f/p; slip = (n_s − n)/n_s × 100%.",
        ("n_s = 120 f / p", "s = (n_s − n) / n_s"),
        _motor,
    ),
    Topic(
        "vdrop",
        "install",
        "Voltage drop",
        "Every circuit you install must stay within the Wiring Rules' 5% voltage drop.",
        "V_d = mV/A·m × I × L ÷ 1000, with the mV/A·m from the cable tables (AS/NZS 3008). The limit is 5% of 230 V = 11.5 V.",
        ("V_d = (mV/A·m × I × L) / 1000", "limit 11.5 V on 230 V"),
        _voltage_drop,
    ),
    Topic(
        "max_length",
        "install",
        "Longest cable run",
        "Working out how far a circuit can run before the cable size goes up.",
        "Transpose the voltage-drop formula: L = V_d × 1000 ÷ (mV/A·m × I).",
        ("L = V_d × 1000 / (mV/A·m × I)",),
        _max_length,
    ),
    Topic(
        "fault_loop",
        "install",
        "Earth fault-loop impedance",
        "A fault must draw enough current to trip the breaker quickly: part of the safety testing on every job.",
        "Z_s = U₀ ÷ I_a, where I_a is the current that trips the breaker instantly.",
        ("Z_s = U₀ / I_a",),
        _fault_loop,
    ),
)

BY_ID = {topic.id: topic for topic in TOPICS}


def make_question(topic_id: str, seed: int) -> Question:
    topic = BY_ID.get(topic_id)
    if topic is None:
        raise KeyError(topic_id)
    rng = random.Random(f"{topic_id}:{seed}")
    prompt, answer, unit, places, steps, hint = topic.make(rng)
    return Question(
        id=f"{topic_id}:{seed}",
        topic=topic_id,
        prompt=prompt,
        answer=float(answer),
        unit=unit,
        places=places,
        steps=tuple(steps),
        hint=hint,
    )
