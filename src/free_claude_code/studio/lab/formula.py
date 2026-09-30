"""Read chemical formulas: which elements, how many, and what they weigh."""

import re
from collections import defaultdict

from . import LabData
from .elements import BY_SYMBOL

_TOKEN = re.compile(r"([A-Z][a-z]?)|(\d+(?:\.\d+)?)|([()\[\]])|([·.*+])")
_SUBSCRIPTS = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")


class FormulaError(ValueError):
    """A formula that can't be read."""


def parse(formula: str) -> dict[str, float]:
    """Element counts, e.g. 'CuSO4·5H2O' → Cu 1, S 1, O 9, H 10."""
    text = formula.translate(_SUBSCRIPTS).replace(" ", "")
    if not text:
        raise FormulaError("An empty formula.")
    total: defaultdict[str, float] = defaultdict(float)
    for part in re.split(r"[·.*+]", text):
        if not part:
            continue
        multiplier = 1.0
        found = re.match(r"^(\d+(?:\.\d+)?)(.*)$", part)
        if found:
            multiplier, part = float(found.group(1)), found.group(2)
        for symbol, count in _group(part).items():
            total[symbol] += count * multiplier
    return {symbol: _tidy(count) for symbol, count in total.items()}


def _tidy(value: float) -> float:
    return int(value) if float(value).is_integer() else round(value, 3)


def _group(text: str) -> defaultdict[str, float]:
    stack: list[defaultdict[str, float]] = [defaultdict(float)]
    position = 0
    while position < len(text):
        char = text[position]
        if char in "([":
            stack.append(defaultdict(float))
            position += 1
            continue
        if char in ")]":
            if len(stack) == 1:
                raise FormulaError(f"A bracket closes with none open in {text!r}.")
            inner = stack.pop()
            position += 1
            count, position = _number(text, position)
            for symbol, amount in inner.items():
                stack[-1][symbol] += amount * count
            continue
        found = re.match(r"[A-Z][a-z]?", text[position:])
        if not found:
            raise FormulaError(f"Can't read {text[position:]!r} in {text!r}.")
        symbol = found.group(0)
        if symbol not in BY_SYMBOL:
            # "Co" vs "C"+"O": try the one-letter element before giving up.
            if symbol[0] in BY_SYMBOL and len(symbol) == 2:
                symbol = symbol[0]
            else:
                raise FormulaError(f"{symbol} isn't an element.")
        position += len(symbol)
        count, position = _number(text, position)
        stack[-1][symbol] += count
    if len(stack) != 1:
        raise FormulaError(f"A bracket is left open in {text!r}.")
    return stack[0]


def _number(text: str, position: int) -> tuple[float, int]:
    found = re.match(r"\d+(?:\.\d+)?", text[position:])
    if not found:
        return 1, position
    return float(found.group(0)), position + len(found.group(0))


def molar_mass(formula: str) -> float:
    """Grams per mole."""
    return round(
        sum(BY_SYMBOL[symbol].mass * count for symbol, count in parse(formula).items()),
        3,
    )


def composition(formula: str) -> list[LabData]:
    """Each element's count and share of the mass, heaviest share first."""
    counts = parse(formula)
    total = sum(BY_SYMBOL[symbol].mass * count for symbol, count in counts.items())
    rows = [
        {
            "symbol": symbol,
            "name": BY_SYMBOL[symbol].name,
            "count": count,
            "mass_percent": round(100 * BY_SYMBOL[symbol].mass * count / total, 2),
        }
        for symbol, count in counts.items()
    ]
    return sorted(rows, key=lambda row: -float(str(row["mass_percent"])))


def pretty(formula: str) -> str:
    """Subscript digits for display: H2SO4 → H₂SO₄ (not leading multipliers)."""
    out: list[str] = []
    previous = ""
    for char in formula:
        if (
            char.isdigit()
            and previous
            and (previous.isalpha() or previous in ")]" or previous in "₀₁₂₃₄₅₆₇₈₉")
        ):
            out.append("₀₁₂₃₄₅₆₇₈₉"[int(char)])
        else:
            out.append(char)
        previous = out[-1]
    return "".join(out)
