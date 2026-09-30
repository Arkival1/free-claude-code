"""Electronics parts and a circuit bench: will the build work, and for how long.

Builds are simple and real: batteries (in series or side by side) power a
set of parts. The bench works out the voltage, the current each part draws,
the resistor each LED needs, how long the battery lasts, and what would
burn out or not switch on, so the app can light up (or smoke) each part.
"""

from dataclasses import dataclass
from typing import Any

from .data import LabData

E12 = (1.0, 1.2, 1.5, 1.8, 2.2, 2.7, 3.3, 3.9, 4.7, 5.6, 6.8, 8.2)


@dataclass(frozen=True, slots=True)
class Part:
    id: str
    name: str
    kind: str
    """power, light, motion, sound, sensor, brain, control, passive, structure,
    charger, regulator, display."""
    icon: str
    volts: float = 0.0
    """Supply: the voltage it gives. Load: the voltage it needs."""
    volts_max: float = 0.0
    """Load: the most it takes before damage (0 = same as volts x 1.3)."""
    milliamps: float = 0.0
    """Load: current drawn. Supply: the most it can give."""
    capacity_mah: float = 0.0
    watts: float = 0.0
    """Solar panels: peak power."""
    grams: float = 0.0
    price: float = 0.0
    """Typical hobby price in US dollars."""
    rechargeable: bool = False
    needs: tuple[str, ...] = ()
    """What else it needs to work: resistor, driver, controller, charger."""
    note: str = ""

    def view(self) -> LabData:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "icon": self.icon,
            "volts": self.volts,
            "volts_max": self.volts_max or round(self.volts * 1.3, 2),
            "milliamps": self.milliamps,
            "capacity_mah": self.capacity_mah,
            "watts": self.watts,
            "grams": self.grams,
            "price": self.price,
            "rechargeable": self.rechargeable,
            "needs": list(self.needs),
            "note": self.note,
        }


def _p(id: str, name: str, kind: str, icon: str, **fields: Any) -> Part:
    return Part(id=id, name=name, kind=kind, icon=icon, **fields)


PARTS: tuple[Part, ...] = (
    # power
    _p(
        "aa",
        "AA battery",
        "power",
        "🔋",
        volts=1.5,
        milliamps=1000,
        capacity_mah=2500,
        grams=23,
        price=0.5,
    ),
    _p(
        "aa-nimh",
        "AA rechargeable (NiMH)",
        "power",
        "🔋",
        volts=1.2,
        milliamps=2000,
        capacity_mah=2000,
        grams=27,
        price=2.5,
        rechargeable=True,
    ),
    _p(
        "9v",
        "9 V battery",
        "power",
        "🔋",
        volts=9.0,
        milliamps=300,
        capacity_mah=550,
        grams=45,
        price=2.0,
    ),
    _p(
        "cr2032",
        "CR2032 coin cell",
        "power",
        "🪙",
        volts=3.0,
        milliamps=15,
        capacity_mah=225,
        grams=3,
        price=0.4,
        note="Can only give a little current.",
    ),
    _p(
        "18650",
        "18650 lithium-ion cell",
        "power",
        "🔋",
        volts=3.7,
        volts_max=4.2,
        milliamps=10000,
        capacity_mah=3000,
        grams=46,
        price=5.0,
        rechargeable=True,
        needs=("charger",),
        note="Needs a protected charger (TP4056).",
    ),
    _p(
        "lipo",
        "LiPo pouch 1000 mAh",
        "power",
        "🔋",
        volts=3.7,
        volts_max=4.2,
        milliamps=2000,
        capacity_mah=1000,
        grams=20,
        price=6.0,
        rechargeable=True,
        needs=("charger",),
    ),
    _p(
        "usb",
        "USB power (5 V)",
        "power",
        "🔌",
        volts=5.0,
        milliamps=2000,
        capacity_mah=0,
        grams=10,
        price=2.0,
        note="Mains adapter: runs for ever.",
    ),
    _p(
        "solar",
        "Solar panel 6 V 1 W",
        "charger",
        "☀️",
        volts=6.0,
        milliamps=166,
        watts=1.0,
        grams=60,
        price=4.0,
        note="In full sun; a tenth of that on a cloudy day.",
    ),
    _p(
        "tp4056",
        "Li-ion charger board (TP4056)",
        "charger",
        "⚡",
        volts=5.0,
        milliamps=1000,
        grams=3,
        price=1.0,
    ),
    _p(
        "boost-5v",
        "5 V boost converter",
        "regulator",
        "⬆️",
        volts=5.0,
        milliamps=1000,
        grams=4,
        price=1.5,
        note="Raises a low battery voltage to a steady 5 V (about 85% efficient).",
    ),
    _p(
        "regulator-3v3",
        "3.3 V regulator",
        "regulator",
        "⬇️",
        volts=3.3,
        milliamps=800,
        grams=2,
        price=0.5,
        note="Drops a higher voltage to 3.3 V.",
    ),
    # light
    _p(
        "led-red",
        "Red LED",
        "light",
        "🔴",
        volts=2.0,
        volts_max=2.2,
        milliamps=20,
        grams=0.3,
        price=0.05,
        needs=("resistor",),
    ),
    _p(
        "led-green",
        "Green LED",
        "light",
        "🟢",
        volts=2.2,
        volts_max=2.5,
        milliamps=20,
        grams=0.3,
        price=0.05,
        needs=("resistor",),
    ),
    _p(
        "led-blue",
        "Blue LED",
        "light",
        "🔵",
        volts=3.0,
        volts_max=3.4,
        milliamps=20,
        grams=0.3,
        price=0.05,
        needs=("resistor",),
    ),
    _p(
        "led-white",
        "White LED",
        "light",
        "⚪",
        volts=3.0,
        volts_max=3.4,
        milliamps=20,
        grams=0.3,
        price=0.05,
        needs=("resistor",),
    ),
    _p(
        "led-power",
        "1 W power LED",
        "light",
        "💡",
        volts=3.2,
        volts_max=3.6,
        milliamps=300,
        grams=1,
        price=0.5,
        needs=("resistor",),
        note="Needs a heatsink.",
    ),
    _p(
        "led-strip",
        "RGB LED strip (30 LEDs, 5 V)",
        "light",
        "🌈",
        volts=5.0,
        volts_max=5.5,
        milliamps=900,
        grams=40,
        price=5.0,
        needs=("controller",),
    ),
    _p(
        "bulb",
        "Torch bulb 3 V",
        "light",
        "💡",
        volts=3.0,
        volts_max=3.6,
        milliamps=300,
        grams=2,
        price=0.5,
    ),
    # motion & sound
    _p(
        "motor",
        "DC hobby motor",
        "motion",
        "⚙️",
        volts=3.0,
        volts_max=6.0,
        milliamps=250,
        grams=18,
        price=1.0,
        note="Draws up to 4x more when starting or stalled.",
    ),
    _p(
        "fan",
        "5 V cooling fan",
        "motion",
        "🌀",
        volts=5.0,
        volts_max=6.0,
        milliamps=150,
        grams=15,
        price=2.5,
    ),
    _p(
        "servo",
        "Micro servo (SG90)",
        "motion",
        "🦾",
        volts=5.0,
        volts_max=6.0,
        milliamps=250,
        grams=9,
        price=2.0,
        needs=("controller",),
    ),
    _p(
        "pump",
        "Mini water pump 5 V",
        "motion",
        "💧",
        volts=5.0,
        volts_max=6.0,
        milliamps=200,
        grams=30,
        price=3.0,
    ),
    _p(
        "vibration",
        "Vibration motor",
        "motion",
        "📳",
        volts=3.0,
        volts_max=3.6,
        milliamps=80,
        grams=1,
        price=0.5,
    ),
    _p(
        "buzzer",
        "Buzzer",
        "sound",
        "🔔",
        volts=5.0,
        volts_max=6.0,
        milliamps=30,
        grams=2,
        price=0.3,
    ),
    _p(
        "speaker",
        "Small speaker + amp",
        "sound",
        "🔊",
        volts=5.0,
        volts_max=5.5,
        milliamps=300,
        grams=20,
        price=3.0,
        needs=("controller",),
    ),
    # brains & sensors
    _p(
        "arduino",
        "Arduino Nano",
        "brain",
        "🧠",
        volts=5.0,
        volts_max=12.0,
        milliamps=40,
        grams=7,
        price=5.0,
        note="Takes 7-12 V on VIN or 5 V on the 5 V pin.",
    ),
    _p(
        "esp32",
        "ESP32 (Wi-Fi + Bluetooth)",
        "brain",
        "📡",
        volts=3.3,
        volts_max=3.6,
        milliamps=120,
        grams=10,
        price=6.0,
        note="Up to 250 mA peaks when Wi-Fi transmits.",
    ),
    _p(
        "raspberry-pi",
        "Raspberry Pi Zero 2 W",
        "brain",
        "🍓",
        volts=5.0,
        volts_max=5.25,
        milliamps=350,
        grams=11,
        price=15.0,
    ),
    _p(
        "temp-sensor",
        "Temperature + humidity sensor (DHT22)",
        "sensor",
        "🌡️",
        volts=3.3,
        volts_max=6.0,
        milliamps=2,
        grams=3,
        price=3.0,
        needs=("controller",),
    ),
    _p(
        "light-sensor",
        "Light sensor (LDR)",
        "sensor",
        "🔆",
        volts=3.3,
        volts_max=12.0,
        milliamps=1,
        grams=0.5,
        price=0.2,
        needs=("controller",),
    ),
    _p(
        "soil-sensor",
        "Soil moisture sensor",
        "sensor",
        "🌱",
        volts=3.3,
        volts_max=5.5,
        milliamps=5,
        grams=4,
        price=1.5,
        needs=("controller",),
    ),
    _p(
        "distance-sensor",
        "Ultrasonic distance sensor",
        "sensor",
        "📏",
        volts=5.0,
        volts_max=5.5,
        milliamps=15,
        grams=9,
        price=1.5,
        needs=("controller",),
    ),
    _p(
        "motion-sensor",
        "Motion sensor (PIR)",
        "sensor",
        "👁️",
        volts=5.0,
        volts_max=12.0,
        milliamps=1,
        grams=6,
        price=1.5,
    ),
    _p(
        "oled",
        'OLED screen 0.96"',
        "display",
        "🖥️",
        volts=3.3,
        volts_max=5.5,
        milliamps=20,
        grams=3,
        price=4.0,
        needs=("controller",),
    ),
    # control & passive
    _p("switch", "Slide switch", "control", "🎚️", grams=1, price=0.2),
    _p("button", "Push button", "control", "🔘", grams=0.5, price=0.1),
    _p(
        "relay",
        "Relay module",
        "control",
        "🔁",
        volts=5.0,
        volts_max=5.5,
        milliamps=70,
        grams=12,
        price=1.5,
    ),
    _p(
        "motor-driver",
        "Motor driver (L298N / DRV8833)",
        "control",
        "🎛️",
        volts=5.0,
        volts_max=12.0,
        milliamps=10,
        grams=25,
        price=2.5,
    ),
    _p(
        "transistor",
        "Transistor (switch for motors)",
        "control",
        "⚡",
        grams=0.3,
        price=0.1,
    ),
    _p("resistor", "Resistor", "passive", "〰️", grams=0.2, price=0.02),
    _p("capacitor", "Capacitor 100 µF", "passive", "🥫", grams=0.5, price=0.1),
    _p("wire", "Hook-up wire", "passive", "➰", grams=2, price=0.2),
    _p("breadboard", "Breadboard", "structure", "🔲", grams=30, price=2.0),
    _p(
        "wheels",
        "Wheels + gear motors pair",
        "motion",
        "🛞",
        volts=5.0,
        volts_max=6.0,
        milliamps=400,
        grams=60,
        price=5.0,
        needs=("driver",),
    ),
    _p("chassis", "Robot chassis", "structure", "🚙", grams=90, price=6.0),
    _p("case", "Enclosure (3D printed PLA)", "structure", "📦", grams=40, price=1.0),
)

BY_ID: dict[str, Part] = {part.id: part for part in PARTS}


def find(text: str) -> Part | None:
    wanted = text.strip().lower()
    if wanted in BY_ID:
        return BY_ID[wanted]
    for part in PARTS:
        if wanted == part.name.lower():
            return part
    for part in PARTS:
        if len(wanted) >= 3 and wanted in part.name.lower():
            return part
    return None


def standard_resistor(ohms: float) -> float:
    """The next E12 value up (so the LED gets a little less than its limit)."""
    if ohms <= 0:
        return 0.0
    decade = 1.0
    while decade * 10 <= ohms:
        decade *= 10
    while decade > ohms:
        decade /= 10
    for step in (*E12, 10.0):
        if step * decade >= ohms - 1e-9:
            return round(step * decade, 2)
    return round(10 * decade, 2)


def simulate_build(
    parts: list[LabData], *, series: bool = True, sun: bool = True
) -> LabData:
    """Power the parts and report what works: volts, amps, runtime, warnings.

    Each entry is {"id", "count"}. Batteries go in series (volts add) unless
    series is False (capacity adds). Every load is wired across the supply
    (through a regulator if one is in the build), LEDs through a resistor.
    """
    chosen: list[tuple[Part, int]] = []
    for entry in parts:
        part = find(str(entry.get("id") or entry.get("name") or ""))
        if part is None:
            raise ValueError(
                f"No part called {entry.get('id') or entry.get('name')!r}."
            )
        raw = entry.get("count")
        count = int(raw) if isinstance(raw, int | float) and 0 < raw <= 50 else 1
        chosen.append((part, count))
    if not chosen:
        raise ValueError("Add some parts to the bench first.")
    ids = {part.id for part, _ in chosen}
    warnings: list[str] = []
    tips: list[str] = []
    cells = [(part, count) for part, count in chosen if part.kind == "power"]
    solar = [(part, count) for part, count in chosen if part.id == "solar"]
    if not cells and solar:
        cells = solar
    if not cells:
        return {
            "works": False,
            "volts": 0.0,
            "parts": [
                {
                    "id": part.id,
                    "name": part.name,
                    "icon": part.icon,
                    "count": count,
                    "state": "off",
                }
                for part, count in chosen
            ],
            "warnings": [
                "Nothing powers this build: add a battery, USB power, or a solar panel."
            ],
            "tips": [],
            "total_ma": 0,
            "runtime_hours": 0,
            "grams": sum(part.grams * count for part, count in chosen),
            "price": round(sum(part.price * count for part, count in chosen), 2),
            "resistors": [],
        }
    kinds = {part.id for part, _ in cells}
    if len(kinds) > 1:
        warnings.append(
            "Don't mix different batteries in one pack: the weaker one drains, heats, and can leak."
        )
    first = cells[0][0]
    count = sum(c for _, c in cells)
    if series:
        volts = sum(part.volts * c for part, c in cells)
        capacity = (
            min(part.capacity_mah for part, _ in cells) if first.capacity_mah else 0.0
        )
        max_ma = min(part.milliamps for part, _ in cells)
    else:
        volts = first.volts
        capacity = sum(part.capacity_mah * c for part, c in cells)
        max_ma = sum(part.milliamps * c for part, c in cells)
    supply = (
        (f"{count} x " if count > 1 else "")
        + first.name
        + (
            " in series"
            if series and count > 1
            else " side by side"
            if count > 1
            else ""
        )
    )
    if first.id == "solar" and not sun:
        volts *= 0.5
        max_ma *= 0.1
        warnings.append("Cloudy: the solar panel gives about a tenth of its power.")
    if (
        first.rechargeable
        and "charger" in first.needs
        and "tp4056" not in ids
        and first.id in {"18650", "lipo"}
    ):
        warnings.append(
            f"{first.name} needs a protected charger board (TP4056) to charge safely."
        )
    if solar and first.id in {"18650", "lipo"} and "tp4056" not in ids:
        warnings.append(
            "Never wire a solar panel straight to a lithium cell: charge it through a TP4056."
        )
    rail = volts
    efficiency = 1.0
    regulated = ""
    if "boost-5v" in ids:
        if volts < 0.9:
            warnings.append("The boost converter needs at least 0.9 V to start.")
        else:
            rail, efficiency, regulated = 5.0, 0.85, "boost-5v"
    elif "regulator-3v3" in ids and volts >= 3.6:
        rail, efficiency, regulated = 3.3, 3.3 / volts, "regulator-3v3"
    has_controller = bool(ids & {"arduino", "esp32", "raspberry-pi"})
    has_driver = bool(ids & {"motor-driver", "transistor", "relay"})
    rows: list[LabData] = []
    resistors: list[LabData] = []
    total_ma = 0.0
    for part, number in chosen:
        if part.kind in {"power", "passive", "structure", "regulator"} or part.id in {
            "solar",
            "tp4056",
            "switch",
            "button",
            "transistor",
        }:
            rows.append(
                {
                    "id": part.id,
                    "name": part.name,
                    "icon": part.icon,
                    "count": number,
                    "state": "ok",
                }
            )
            continue
        limit = part.volts_max or part.volts * 1.3
        state = "on"
        reason = ""
        current = part.milliamps
        if part.id == "arduino" and rail >= 7:
            state = "on"
        elif part.needs and "resistor" in part.needs:
            if rail < part.volts:
                state, reason, current = (
                    "dim",
                    f"needs {part.volts} V, gets {rail:.1f} V",
                    part.milliamps * 0.1,
                )
            else:
                ohms = (rail - part.volts) / (part.milliamps / 1000)
                if ohms < 1:
                    state = "on"
                else:
                    value = standard_resistor(ohms)
                    power = (part.milliamps / 1000) ** 2 * value
                    resistors.append(
                        {
                            "for": part.name,
                            "ohms": value,
                            "exact_ohms": round(ohms, 1),
                            "watts": round(power, 3),
                            "rating": "¼ W"
                            if power < 0.2
                            else "½ W"
                            if power < 0.4
                            else "1 W+",
                        }
                    )
                    current = (
                        (rail - part.volts) / value * 1000 if value else part.milliamps
                    )
                    tips.append(
                        f"Put a {_ohms(value)} resistor in series with each {part.name.lower()} ({rail:.1f} V - {part.volts} V) ÷ {part.milliamps / 1000:g} A."
                    )
        elif rail > limit:
            state, reason = (
                "burnt",
                f"{rail:.1f} V is more than its {limit:.1f} V limit",
            )
        elif rail < part.volts * 0.75:
            state, reason, current = (
                "off",
                f"needs about {part.volts} V, gets {rail:.1f} V",
                0,
            )
        elif rail < part.volts * 0.9:
            state, reason, current = (
                "weak",
                f"a bit under its {part.volts} V",
                part.milliamps * 0.7,
            )
        if "controller" in part.needs and not has_controller and state == "on":
            state, reason = (
                "idle",
                "needs a microcontroller (Arduino or ESP32) to tell it what to do",
            )
        if "driver" in part.needs and not has_driver and state == "on":
            warnings.append(
                f"{part.name}: use a motor driver; a microcontroller pin can only give about 20 mA."
            )
        if (
            part.kind == "motion"
            and has_controller
            and not has_driver
            and part.id not in {"servo"}
        ):
            warnings.append(
                f"{part.name} draws {part.milliamps:g} mA: switch it with a transistor or motor driver, not straight from a pin."
            )
        if state == "burnt":
            warnings.append(
                f"{part.name} would burn out: {reason}. Add a regulator or use fewer cells."
            )
        elif state in {"off", "weak", "dim"}:
            warnings.append(
                f"{part.name} {"won't switch on" if state == 'off' else 'runs weakly'}: {reason}."
            )
        if state not in {"burnt", "off"}:
            total_ma += current * number
        rows.append(
            {
                "id": part.id,
                "name": part.name,
                "icon": part.icon,
                "count": number,
                "state": state,
                "reason": reason,
                "milliamps": round(current, 1),
            }
        )
    draw_from_cells = total_ma * (rail / volts) / efficiency if volts else total_ma
    if max_ma and draw_from_cells > max_ma * 1.05:
        warnings.append(
            f"The parts want {draw_from_cells:.0f} mA but the {first.name.lower()} can only give about {max_ma:.0f} mA: things will brown out."
        )
    runtime = capacity / draw_from_cells if capacity and draw_from_cells else 0.0
    if first.id == "usb":
        runtime = float("inf")
    works = not any(row.get("state") in {"burnt", "off"} for row in rows) and not (
        max_ma and draw_from_cells > max_ma * 1.05
    )
    watts = rail * total_ma / 1000
    return {
        "works": works,
        "supply": supply,
        "volts": round(volts, 2),
        "rail_volts": round(rail, 2),
        "regulated_by": regulated,
        "capacity_mah": capacity,
        "total_ma": round(draw_from_cells, 1),
        "watts": round(watts, 2),
        "runtime_hours": None if runtime == float("inf") else round(runtime, 1),
        "runtime_text": _runtime(runtime),
        "parts": rows,
        "resistors": resistors,
        "warnings": list(dict.fromkeys(warnings)),
        "tips": list(dict.fromkeys(tips)),
        "grams": round(sum(part.grams * count for part, count in chosen), 1),
        "price": round(sum(part.price * count for part, count in chosen), 2),
    }


def _ohms(value: float) -> str:
    return f"{value / 1000:g} kΩ" if value >= 1000 else f"{value:g} Ω"


def _runtime(hours: float) -> str:
    if hours == float("inf"):
        return "Runs as long as it's plugged in."
    if hours <= 0:
        return "Doesn't run."
    if hours < 1:
        return f"About {hours * 60:.0f} minutes per charge."
    if hours < 48:
        return f"About {hours:.1f} hours."
    return f"About {hours / 24:.0f} days."
