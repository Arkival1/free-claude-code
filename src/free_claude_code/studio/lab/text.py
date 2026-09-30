"""What the agents read back from the Lab: short, factual summaries."""

from . import chemicals, materials, tech
from .bench import LabBench
from .data import LabData
from .elements import BY_SYMBOL, ELEMENTS
from .formula import pretty
from .sim import LabError


def describe_project(project: LabData) -> str:
    data = project.get("data")
    if not isinstance(data, dict):
        return f"Made {project.get('name')}."
    if project.get("kind") == "build":
        return describe_build(project)
    lines = [
        f"Made {data.get('name')} ({data.get('batch_g')} g batch, shown in a "
        f"{data.get('container')} on the Lab bench). Ingredients:"
    ]
    for row in data.get("ingredients") or []:
        if not isinstance(row, dict):
            continue
        formula = str(row.get("formula") or row.get("typical_formula") or "")
        shown = f" [{pretty(formula)}]" if formula else ""
        lines.append(
            f"- {row.get('name')}{shown}: {row.get('percent')}% "
            f"({row.get('grams')} g) - {row.get('purpose')}"
        )
    elements = [
        f"{row.get('symbol')} {row.get('percent')}%"
        for row in (data.get("elements") or [])[:8]
        if isinstance(row, dict)
    ]
    if elements:
        lines.append("By element: " + ", ".join(elements) + ".")
    if data.get("ph"):
        lines.append(f"Target pH: {data.get('ph')}.")
    if data.get("safety"):
        lines.append(f"Safety: {data.get('safety')}")
    if data.get("source") == "ai":
        lines.append(
            "This formula was written by the Lab's AI: test a small batch first."
        )
    if data.get("unknown"):
        lines.append(
            "Not on the shelf (left out): " + ", ".join(map(str, data["unknown"])) + "."
        )
    return "\n".join(lines)


def describe_mix(result: LabData) -> str:
    vessel = result.get("vessel")
    assert isinstance(vessel, dict)
    lines = [str(result.get("summary") or "")]
    lines.extend(
        f"Equation: {reaction.get('equation')}"
        for reaction in result.get("reactions") or []
        if isinstance(reaction, dict)
    )
    lines.extend(f"You see: {seen}" for seen in result.get("observations") or [])
    lines.append(
        f"Liquid colour {vessel.get('colour')}, {vessel.get('temperature_c')} °C"
        + (f", pH {vessel.get('ph')}" if vessel.get("ph") is not None else "")
        + "."
    )
    lines.extend(
        f"Warning: {hazard.get('text')}"
        for hazard in result.get("hazards") or []
        if isinstance(hazard, dict) and hazard.get("level") in {"danger", "warning"}
    )
    prediction = result.get("prediction")
    if isinstance(prediction, dict):
        lines.append(f"AI prediction (not from the rules): {prediction.get('happens')}")
    return "\n".join(line for line in lines if line)


def describe_build(result: LabData) -> str:
    data = result.get("data") if isinstance(result.get("data"), dict) else result
    assert isinstance(data, dict)
    works = "works" if data.get("works") else "doesn't work yet"
    lines = [
        f"{data.get('name')}: {works}. Power: {data.get('supply')} "
        f"({data.get('volts')} V, {data.get('total_ma')} mA). {data.get('runtime_text')}"
    ]
    for row in data.get("parts") or []:
        if isinstance(row, dict) and row.get("state") not in {"ok"}:
            reason = f" ({row.get('reason')})" if row.get("reason") else ""
            lines.append(
                f"- {row.get('name')} x{row.get('count')}: {row.get('state')}{reason}"
            )
    lines.extend(f"Tip: {tip}" for tip in data.get("tips") or [])
    lines.extend(f"Warning: {warning}" for warning in data.get("warnings") or [])
    lines.append(f"Parts cost about ${data.get('price')}, weigh {data.get('grams')} g.")
    return "\n".join(lines)


def describe_material(result: LabData) -> str:
    data = result.get("data") if isinstance(result.get("data"), dict) else result
    assert isinstance(data, dict)
    material = data.get("material")
    tests = data.get("tests")
    assert isinstance(material, dict) and isinstance(tests, dict)
    pull = tests.get("pull")
    assert isinstance(pull, dict)
    return (
        f"{material.get('name')}: density {material.get('density')} g/cm³, "
        f"tensile strength {material.get('strength')} MPa, stiffness "
        f"{material.get('stiffness')} GPa, melts at {material.get('melts')} °C, "
        f"{'conducts electricity' if material.get('conductor') else 'insulates'}. "
        f"Pull test: {pull.get('word')}. {data.get('note')}"
    )


async def find(bench: LabBench, text: str) -> str:
    wanted = text.strip()
    if not wanted:
        raise LabError("Say what to look up.")
    element = BY_SYMBOL.get(wanted) or next(
        (e for e in ELEMENTS if e.name.lower() == wanted.lower()), None
    )
    if element is not None:
        view = element.view()
        flame = view["flame"]
        return (
            f"{element.name} ({element.symbol}), element {element.number}: "
            f"{element.category.replace('-', ' ')}, {element.state} at room "
            f"temperature, atomic mass {element.mass}. {view['uses']}"
            + (f" Flame colour: {flame['name']}." if isinstance(flame, dict) else "")
        )
    material = materials.find(wanted)
    part = tech.find(wanted)
    shelf = chemicals.find(wanted)
    if shelf is None and material is not None:
        return str(material.view())
    if shelf is None and part is not None:
        return str(part.view())
    view = await bench.lookup(wanted)
    hazards = ", ".join(
        str(h["text"]) for h in view.get("hazards") or [] if isinstance(h, dict)
    )
    return (
        f"{view.get('name')}: formula {pretty(str(view.get('formula') or '?'))}, "
        f"{view.get('molar_mass')} g/mol, {view.get('kind')}, {view.get('state')}."
        + (f" Hazards: {hazards}." if hazards else "")
        + (f" {view.get('note')}" if view.get("note") else "")
        + (" (Learned from PubChem.)" if view.get("source") == "pubchem" else "")
    )
