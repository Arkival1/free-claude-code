"""Every trading platform FCC can connect to, and how to make each one.

Each entry says which markets the platform trades, which keys it needs and
where to get them, and how it suits someone in Australia. Keys are kept in
one owner-only file and never sent back to the app.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

import httpx

from free_claude_code.core.json_types import JsonObject

from ..data import MarketData
from .base import Broker


@dataclass(frozen=True, slots=True)
class KeyField:
    key: str
    label: str
    secret: bool = True
    placeholder: str = ""
    optional: bool = False
    choices: tuple[str, ...] = ()


Factory = Callable[
    [Mapping[str, str], MarketData, httpx.AsyncBaseTransport | None], Broker
]


@dataclass(frozen=True, slots=True)
class BrokerSpec:
    id: str
    name: str
    markets: tuple[str, ...]
    """us, asx, crypto (meme coins trade where the platform lists them)."""
    what: str
    get_keys: str
    australia: str
    fields: tuple[KeyField, ...] = ()
    factory: Factory | None = field(default=None, compare=False)

    def view(self, values: Mapping[str, str] | None) -> JsonObject:
        values = values or {}
        return {
            "id": self.id,
            "name": self.name,
            "markets": list(self.markets),
            "what": self.what,
            "get_keys": self.get_keys,
            "australia": self.australia,
            "connected": bool(values)
            and all(values.get(item.key) for item in self.fields if not item.optional),
            "fields": [
                {
                    "key": item.key,
                    "label": item.label,
                    "secret": item.secret,
                    "placeholder": item.placeholder,
                    "optional": item.optional,
                    "choices": list(item.choices),
                    "set": bool(values.get(item.key)),
                    # Only plain settings come back; secrets never do.
                    "value": "" if item.secret else values.get(item.key, ""),
                }
                for item in self.fields
            ],
        }


PAPER = BrokerSpec(
    id="paper",
    name="Paper account (practice)",
    markets=("us", "asx", "crypto"),
    what="Practice money on real prices: every market, no keys, no risk.",
    get_keys="Nothing to set up.",
    australia="Prices in AUD; ASX whole shares and the $500 first-parcel rule apply.",
)

BROKERS: dict[str, BrokerSpec] = {PAPER.id: PAPER}


def register(spec: BrokerSpec) -> BrokerSpec:
    BROKERS[spec.id] = spec
    return spec


class BrokerSetupError(ValueError):
    """A platform can't be used yet; the message says what's missing."""


def make_broker(
    broker_id: str,
    values: Mapping[str, str],
    *,
    data: MarketData,
    transport: httpx.AsyncBaseTransport | None = None,
) -> Broker:
    spec = BROKERS.get(broker_id)
    if spec is None or spec.factory is None:
        raise BrokerSetupError(f"FCC doesn't know a platform called {broker_id!r}.")
    missing = [
        item.label
        for item in spec.fields
        if not item.optional and not values.get(item.key)
    ]
    if missing:
        raise BrokerSetupError(
            f"{spec.name} needs: {', '.join(missing)}. Add them on the Trading page."
        )
    try:
        return spec.factory(values, data, transport)
    except ValueError as error:
        raise BrokerSetupError(f"{spec.name}: {error}") from error


def environment_of(broker_id: str, values: Mapping[str, str]) -> str:
    """Whether a key set is for a practice (demo or paper) account or a real
    one, from the platform's own setting."""
    if broker_id == "alpaca" and values.get("account", "paper") != "live":
        return "practice"
    if broker_id == "swyftx" and values.get("environment", "demo") != "live":
        return "practice"
    if broker_id == "hyperliquid" and values.get("environment") == "testnet":
        return "practice"
    return "live"


def secret_fields() -> dict[str, set[str]]:
    """Each platform's secret field names (for blanking out of the feed)."""
    return {
        spec.id: {item.key for item in spec.fields if item.secret}
        for spec in BROKERS.values()
    }


def check_values(broker_id: str, values: Mapping[str, str]) -> dict[str, str]:
    """Keep only the platform's own fields, trimmed; choices must be valid."""
    spec = BROKERS.get(broker_id)
    if spec is None:
        raise BrokerSetupError(f"FCC doesn't know a platform called {broker_id!r}.")
    cleaned: dict[str, str] = {}
    for item in spec.fields:
        value = str(values.get(item.key) or "").strip()
        if item.choices and value and value not in item.choices:
            raise BrokerSetupError(
                f"{item.label} must be one of: {', '.join(item.choices)}."
            )
        if value:
            cleaned[item.key] = value
    return cleaned
