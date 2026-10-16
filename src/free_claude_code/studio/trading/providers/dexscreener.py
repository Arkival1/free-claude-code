"""DexScreener: liquidity, age, and buying pressure for meme coins.

It reads decentralised exchanges, where most meme coins start. FCC only uses
it for research and rug-pull warning signs; it never trades there.
"""

import time
from dataclasses import dataclass

from free_claude_code.core.json_types import JsonObject

from ...resilience import Web

API = "https://api.dexscreener.com"


@dataclass(frozen=True, slots=True)
class DexFacts:
    """The deepest trading pair found for a token."""

    symbol: str
    name: str
    chain: str
    dex: str
    price_usd: float | None
    liquidity_usd: float
    volume_24h: float
    fdv: float | None
    age_days: float | None
    buys_24h: int
    sells_24h: int
    change_24h: float | None
    pairs: int
    url: str = ""

    @property
    def buy_ratio(self) -> float | None:
        total = self.buys_24h + self.sells_24h
        return self.buys_24h / total if total else None

    def warnings(self, *, min_liquidity: float, min_age_days: float) -> list[str]:
        """Rug-pull and thin-market warning signs, in plain words."""
        found: list[str] = []
        if self.liquidity_usd < min_liquidity:
            found.append(
                f"thin liquidity (${self.liquidity_usd:,.0f} < ${min_liquidity:,.0f})"
            )
        if self.age_days is not None and self.age_days < min_age_days:
            found.append(f"new token ({self.age_days:.1f} days old)")
        if self.fdv and self.liquidity_usd and self.fdv / self.liquidity_usd > 200:
            found.append("valuation far above its liquidity")
        ratio = self.buy_ratio
        if ratio is not None and ratio < 0.35:
            found.append("mostly selling in the last day")
        if (
            self.volume_24h
            and self.liquidity_usd
            and self.volume_24h > 20 * self.liquidity_usd
        ):
            found.append("volume many times its liquidity (possible wash trading)")
        return found

    def view(self) -> JsonObject:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "chain": self.chain,
            "dex": self.dex,
            "price_usd": self.price_usd,
            "liquidity_usd": round(self.liquidity_usd),
            "volume_24h": round(self.volume_24h),
            "fdv": self.fdv,
            "age_days": round(self.age_days, 1) if self.age_days is not None else None,
            "buys_24h": self.buys_24h,
            "sells_24h": self.sells_24h,
            "change_24h": self.change_24h,
            "pairs": self.pairs,
            "url": self.url,
        }


class DexScreener:
    def __init__(self, web: Web) -> None:
        self._web = web

    async def facts(
        self, query: str, *, chain: str = "", address: str = ""
    ) -> DexFacts | None:
        """The deepest pair for a symbol, or for a token's address."""
        if address:
            body = await self._web.get_json(
                f"{API}/token-pairs/v1/{chain}/{address}", what="DexScreener"
            )
            pairs = body if isinstance(body, list) else []
        else:
            body = await self._web.get_json(
                f"{API}/latest/dex/search", params={"q": query}, what="DexScreener"
            )
            pairs = body.get("pairs") if isinstance(body, dict) else []
        return best_pair(
            pairs if isinstance(pairs, list) else [], query, address=address
        )

    async def boosted(self) -> list[JsonObject]:
        """Tokens being promoted right now: what crowds are being pointed at."""
        body = await self._web.get_json(
            f"{API}/token-boosts/top/v1", what="DexScreener"
        )
        return (
            [dict(item) for item in body if isinstance(item, dict)]
            if isinstance(body, list)
            else []
        )


def best_pair(
    pairs: list[object], query: str, *, address: str = "", now: float | None = None
) -> DexFacts | None:
    wanted = query.upper()
    chosen: dict[str, object] | None = None
    best_liquidity = -1.0
    matching = 0
    for pair in pairs:
        if not isinstance(pair, dict):
            continue
        raw = pair.get("baseToken")
        base = raw if isinstance(raw, dict) else {}
        if address:
            if str(base.get("address", "")).lower() != address.lower():
                continue
        elif str(base.get("symbol", "")).upper() != wanted:
            continue
        matching += 1
        liquidity = _number(_get(pair, "liquidity", "usd")) or 0.0
        if liquidity > best_liquidity:
            chosen, best_liquidity = pair, liquidity
    if chosen is None:
        return None
    raw = chosen.get("baseToken")
    base = raw if isinstance(raw, dict) else {}
    created = _number(chosen.get("pairCreatedAt"))
    current = now if now is not None else time.time()
    return DexFacts(
        symbol=str(base.get("symbol") or query).upper(),
        name=str(base.get("name") or ""),
        chain=str(chosen.get("chainId") or ""),
        dex=str(chosen.get("dexId") or ""),
        price_usd=_number(chosen.get("priceUsd")),
        liquidity_usd=max(best_liquidity, 0.0),
        volume_24h=_number(_get(chosen, "volume", "h24")) or 0.0,
        fdv=_number(chosen.get("fdv")),
        age_days=(current - created / 1000) / 86_400 if created else None,
        buys_24h=int(_number(_get(chosen, "txns", "h24", "buys")) or 0),
        sells_24h=int(_number(_get(chosen, "txns", "h24", "sells")) or 0),
        change_24h=_number(_get(chosen, "priceChange", "h24")),
        pairs=matching,
        url=str(chosen.get("url") or ""),
    )


def _get(data: object, *path: str) -> object:
    for key in path:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None
