"""What the Lab won't make: weapons, explosives, drugs, and poisons.

Dangerous household mixes still simulate (with warnings), because knowing
that bleach and ammonia make a toxic gas keeps people safe. Recipes and
builds meant to hurt people don't.
"""

import re

_ALLOWED = re.compile(
    r"\b(bath|seed|photo|glitter|fizz(y|ing)?|shower|salt)[ -]?bombs?\b",
    re.IGNORECASE,
)
_BLOCKED: tuple[tuple[str, str], ...] = (
    (
        r"\b(bombs?|explosives?|detonat\w*|ied|grenades?|landmines?|dynamite|tnt|c-?4|semtex|nitroglycerin\w*|pipe ?bomb)\b",
        "explosives",
    ),
    (
        r"\b(gun ?powder|black ?powder|flash ?powder|thermite|napalm|molotov|rocket fuel|incendiar\w*)\b",
        "incendiaries and explosives",
    ),
    (
        r"\b(nerve (agent|gas)|sarin|vx|tabun|soman|novichok|mustard gas|phosgene|ricin|abrin|anthrax|botulinum|chemical weapons?|bio ?weapons?|toxic gas|poison gas)\b",
        "chemical or biological weapons",
    ),
    (
        r"\b(poison(s|ous|ing)?(?! ivy)|lethal dose|untraceable)\b|\bto kill (a |an |my |the )?(someone|somebody|people|person|him|her|them|neighbou?r|animals?|dogs?|cats?)\b",
        "poisons",
    ),
    (
        r"\b(meth(amphetamine)?|crystal meth|cocaine|heroin|fentanyl|lsd|mdma|ecstasy|ghb|ketamine|pcp|dmt|opioids?|narcotics?|illegal drugs?|recreational drugs?)\b",
        "illegal drugs",
    ),
    (
        r"\b(guns?|firearms?|rifles?|pistols?|ammo|ammunition|bullets?|silencers?|suppressors?|weapons?|tasers?|stun ?guns?)\b",
        "weapons",
    ),
)


def refusal(text: str) -> str | None:
    """Why the Lab won't do this, or None when it's fine."""
    cleaned = _ALLOWED.sub(" ", text)
    for pattern, what in _BLOCKED:
        if re.search(pattern, cleaned, re.IGNORECASE):
            return (
                f"The Lab doesn't make {what}. It's for safe science: "
                "products, materials, and gadgets."
            )
    return None
