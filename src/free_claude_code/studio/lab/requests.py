"""Read Lab jobs out of what the user tells the main AI.

A small model on this PC rarely picks the lab tool out of two dozen, so
'make shampoo' or 'mix vinegar and baking soda' are carried out by Studio
before the main AI answers, the same way orders for the agents are.
"""

import re
from dataclasses import dataclass, field

from . import chemicals
from .data import LabData

_LEAD = re.compile(
    r"^\s*(?:(?:hey|ok|okay|yo)\s+)?(?:\w+\s*[,:!]\s*)?(?:please\s+)?"
    r"(?:(?:can|could|would|will)\s+you\s+(?:please\s+)?|i\s+(?:want|need)\s+you\s+to\s+"
    r"|let'?s\s+|go\s+)?",
    re.I,
)
_MAKE = re.compile(
    r"^(?:make|create|formulate|brew|build|design|craft|invent|cook\s+up|whip\s+up)"
    r"\s+(?:me\s+|us\s+)?(?P<thing>.+)$",
    re.I | re.S,
)
_MIX = re.compile(
    r"^(?:mix|combine|react|blend|heat|warm|boil|burn|ignite)\s+(?P<things>.+)$",
    re.I | re.S,
)
_VERB = (
    r"(?:make|create|formulate|brew|build|design|craft|invent|cook\s+up|whip\s+up|"
    r"mix|combine|react|blend|heat|warm|boil|burn|ignite)\b"
)
_CLAUSE = re.compile(
    rf"(?:^|\b(?:and|then|to|please)\s+)(?P<rest>{_VERB}.*)$", re.I | re.S
)
_IN_THE_LAB = re.compile(
    r"\s*(?:,\s*)?\b(?:in|at|with|using|on|from|to|into)\s+(?:the\s+|my\s+)?"
    r"lab(?:oratory)?\b"
    r"|\s*\blab\s*:\s*",
    re.I,
)
_TAIL = re.compile(r"[\s,;]*(?:please|pls|for me|thanks|thank you)?[\s.!?,;]*$", re.I)
_JOINERS = re.compile(r"\s*(?:,|\+|&|\band\b|\bwith\b|\binto\b|\bto\b)\s*", re.I)
_HEAT = re.compile(r"\b(?:heat(?:ed|ing)?|hot|boil(?:ing)?|warm(?:ed)?)\b", re.I)
_FLAME = re.compile(r"\b(?:flame|fire|burn(?:ing)?|ignite)\b", re.I)
_EXTRAS = re.compile(
    r"\b(?:heat(?:ed|ing)?|hot|boil(?:ing)?|warm(?:ed)?|flame|fire|burn(?:ing)?|"
    r"ignite|together|them|it|up|some|a\s+bit\s+of|a\s+little)\b",
    re.I,
)
_ARTICLE = re.compile(r"^(?:a|an|the|some)\s+", re.I)
MIX_AMOUNT = 50


@dataclass(frozen=True, slots=True)
class LabJob:
    """One Lab job a message asks for."""

    action: str
    """make or mix."""
    request: str
    items: list[LabData] = field(default_factory=list)
    heat: bool = False
    flame: bool = False


def mentions_lab(text: str) -> bool:
    return bool(re.search(r"\blab(?:oratory)?\b", text, re.I))


def lab_job(text: str, *, in_lab: bool) -> LabJob | None:
    """The Lab job in a message, or None.

    In the Lab's own chat any 'make ...' or 'mix ...' is a Lab job; anywhere
    else the message has to mention the Lab, so 'make me a website' still
    goes to the Builder.
    """
    if not in_lab and not mentions_lab(text):
        return None
    said = _IN_THE_LAB.sub(" ", text).strip(" \t\n,;:.-")
    lead = _LEAD.match(said)
    if lead is not None:
        said = said[lead.end() :]
    said = _TAIL.sub("", said).strip()
    clause = _CLAUSE.search(said)
    if clause is not None:
        said = clause.group("rest").strip()
    mix = _MIX.match(said)
    if mix:
        items = _chemicals(mix.group("things"))
        if len(items) >= 2:
            return LabJob(
                action="mix",
                request=said,
                items=items,
                heat=bool(_HEAT.search(said)),
                flame=bool(_FLAME.search(said)),
            )
    make = _MAKE.match(said)
    if make:
        thing = _ARTICLE.sub("", make.group("thing").strip())
        if thing and len(thing) <= 160:
            return LabJob(action="make", request=thing)
    return None


def _chemicals(text: str) -> list[LabData]:
    """'vinegar and baking soda' as shelf chemicals, each named once."""
    found: list[LabData] = []
    for part in _JOINERS.split(_EXTRAS.sub(" ", text)):
        name = _ARTICLE.sub("", " ".join(part.split()))
        if not name:
            continue
        chemical = chemicals.resolve(name)
        if chemical is not None and all(item["id"] != chemical.id for item in found):
            found.append({"id": chemical.id, "amount": MIX_AMOUNT})
    return found
