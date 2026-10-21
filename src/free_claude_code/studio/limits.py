"""Telling a provider's limits apart: a used-up allowance for the day
(stop and say so) or a brief per-minute rate limit (wait a moment, go on).

One definition, used by every agent's carry-on and by the Changer."""

import re

_DAILY_WORDS = re.compile(r"per ?day|daily|resource.?exhausted", re.IGNORECASE)
_MINUTE_WORDS = re.compile(r"per ?minute|per ?second", re.IGNORECASE)
_QUOTA = re.compile(r"quota", re.IGNORECASE)
_RATE = re.compile(r"\b429\b|rate.?limit|too many requests", re.IGNORECASE)


def daily_limit(text: str) -> bool:
    """A used-up allowance for the day, or a quota that names no time at all
    (like 'exceeded your current quota'); never a per-minute limit."""
    if _DAILY_WORDS.search(text):
        return True
    return bool(_QUOTA.search(text)) and not _MINUTE_WORDS.search(text)


def brief_limit(text: str) -> bool:
    """A short rate limit (requests per minute): worth waiting a moment."""
    if _MINUTE_WORDS.search(text):
        return True
    return bool(_RATE.search(text)) and not daily_limit(text)
