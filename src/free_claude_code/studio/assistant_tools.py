"""Everyday helpers for the main AI and the Helper: maths, times, and to-dos."""

import ast
import math
import operator
import re
from collections.abc import Callable
from datetime import datetime, timedelta

MAX_POWER = 10_000
MAX_RESULT_DIGITS = 60
_BINARY: dict[type[ast.operator], Callable[[float, float], float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY: dict[type[ast.unaryop], Callable[[float], float]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}
_FUNCTIONS: dict[str, Callable[..., float]] = {
    "sqrt": math.sqrt,
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "floor": math.floor,
    "ceil": math.ceil,
    "log": math.log,
    "log10": math.log10,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
}
_CONSTANTS = {"pi": math.pi, "e": math.e}


class CalculationError(ValueError):
    """Raised when an expression is not plain arithmetic."""


def calculate(expression: str) -> float | int:
    """Work out plain arithmetic safely: numbers, + - * / // % **, (), and a
    few maths functions. Nothing else is evaluated."""
    cleaned = (
        expression.replace("\u00d7", "*")
        .replace("÷", "/")
        .replace("^", "**")
        .replace(",", "")
    )
    cleaned = re.sub(r"(\d+(?:\.\d+)?)\s*%\s*of\s*", r"(\1/100)*", cleaned, flags=re.I)
    if len(cleaned) > 300:
        raise CalculationError("That expression is too long.")
    try:
        tree = ast.parse(cleaned.strip(), mode="eval")
    except SyntaxError as error:
        raise CalculationError(f"Not a sum I can work out: {expression}") from error
    result = _value(tree.body)
    if isinstance(result, float) and result.is_integer() and abs(result) < 1e15:
        return int(result)
    return result


def _value(node: ast.AST) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
        if isinstance(node.value, bool):
            raise CalculationError("Only numbers can be calculated.")
        return node.value
    if isinstance(node, ast.Name) and node.id in _CONSTANTS:
        return _CONSTANTS[node.id]
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
        left, right = _value(node.left), _value(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > MAX_POWER:
            raise CalculationError("That power is too large.")
        try:
            result = _BINARY[type(node.op)](left, right)
        except ZeroDivisionError as error:
            raise CalculationError("Division by zero.") from error
        if isinstance(result, int) and len(str(abs(result))) > MAX_RESULT_DIGITS:
            raise CalculationError("The result is too large.")
        return result
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_value(node.operand))
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in _FUNCTIONS
        and not node.keywords
    ):
        try:
            return _FUNCTIONS[node.func.id](*(_value(arg) for arg in node.args))
        except (ValueError, TypeError) as error:
            raise CalculationError(f"{node.func.id}: {error}") from error
    raise CalculationError("Only numbers, + - * / % **, brackets, and maths functions.")


_IN = re.compile(
    r"^in\s+(\d+(?:\.\d+)?|an?|one)\s*(minutes?|mins?|m|hours?|hrs?|h|days?|d|weeks?|w)$",
    re.I,
)
_CLOCK = re.compile(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$", re.I)
_UNITS = {"m": "minutes", "h": "hours", "d": "days", "w": "weeks"}


def parse_when(text: str, *, now: datetime) -> datetime:
    """Read 'in 20 minutes', 'tomorrow 9am', 'at 17:30', or '2026-10-01 14:00'."""
    wanted = " ".join(text.strip().lower().split())
    if not wanted:
        raise ValueError("Say when.")
    moved = _IN.match(wanted)
    if moved:
        raw, unit = moved.groups()
        amount = 1.0 if raw in {"a", "an", "one"} else float(raw)
        return now + timedelta(**{_UNITS[unit[0]]: amount})
    try:
        if re.match(r"^\d{4}-\d{2}-\d{2}", wanted):
            return datetime.fromisoformat(wanted.replace(" ", "T", 1))
        return _day_and_time(wanted, now)
    except ValueError as error:
        raise ValueError(
            f"Could not read the time '{text}'. Use 'in 20 minutes', 'tomorrow 9am', "
            "'at 17:30', or '2026-10-01 14:00'."
        ) from error


def _day_and_time(wanted: str, now: datetime) -> datetime:
    day = now.date()
    rest = wanted
    for word, shift in (("today", 0), ("tonight", 0), ("tomorrow", 1)):
        if rest.startswith(word):
            day = day + timedelta(days=shift)
            rest = rest[len(word) :].strip()
            if word == "tonight" and not rest:
                rest = "8pm"
            break
    rest = rest.removeprefix("at ").strip() or "9am"
    clock = _CLOCK.match(rest)
    if not clock:
        raise ValueError(rest)
    hour, minute, half = int(clock.group(1)), int(clock.group(2) or 0), clock.group(3)
    if half:
        hour = hour % 12 + (12 if half.lower() == "pm" else 0)
    if hour > 23 or minute > 59:
        raise ValueError(rest)
    when = datetime.combine(day, datetime.min.time()).replace(hour=hour, minute=minute)
    if when <= now and not wanted.startswith(("today", "tonight", "tomorrow")):
        when += timedelta(days=1)
    return when


def describe_time(moment: datetime, *, now: datetime) -> str:
    """'today 17:30', 'tomorrow 09:00', or 'Thu 2 Oct 09:00'."""
    days = (moment.date() - now.date()).days
    clock = moment.strftime("%H:%M")
    if days == 0:
        return f"today {clock}"
    if days == 1:
        return f"tomorrow {clock}"
    return f"{moment.strftime('%a')} {moment.day} {moment.strftime('%b')} {clock}"


def now_line(now: datetime) -> str:
    """The date and time, for an agent that cannot see a clock."""
    date = f"{now.strftime('%A')} {now.day} {now.strftime('%B %Y, %H:%M')}"
    return f"Now: {date} (the user's local time)."
