"""Which FCC this is: the full Studio, or the Orb (Jarvis and two advisers).

The Orb download carries a one-word ``EDITION`` file beside this module;
``STUDIO_EDITION`` in the settings overrides it.
"""

from pathlib import Path

FULL = "full"
ORB = "orb"
EDITIONS = (FULL, ORB)
_MARK = Path(__file__).with_name("EDITION")


def packaged_edition() -> str:
    """The edition this download was packed as (the full Studio if unmarked)."""
    try:
        text = _MARK.read_text(encoding="utf-8").strip().lower()
    except OSError:
        return FULL
    return text if text in EDITIONS else FULL
