"""CoinGecko: prices and history for coins Yahoo lacks, trends, and meme coins.

The free public API allows a few calls a minute; a free demo key (Settings,
Trading) raises that. Answers are cached by the market data layer.
"""

from ...resilience import Web
from ..indicators import Bar

API = "https://api.coingecko.com/api/v3"


class CoinGecko:
    def __init__(self, web: Web, *, key: str = "") -> None:
        self._web = web
        self._key = key

    def _headers(self) -> dict[str, str]:
        return {"x-cg-demo-api-key": self._key} if self._key else {}

    async def find_id(self, symbol: str) -> str:
        """The CoinGecko id for a coin symbol (the best-ranked match)."""
        body = await self._web.get_json(
            f"{API}/search",
            params={"query": symbol},
            headers=self._headers(),
            what="CoinGecko",
        )
        coins = body.get("coins") if isinstance(body, dict) else None
        best = ""
        best_rank = 10**9
        for coin in coins if isinstance(coins, list) else []:
            if not isinstance(coin, dict):
                continue
            if str(coin.get("symbol", "")).upper() != symbol.upper():
                continue
            rank = coin.get("market_cap_rank")
            rank = rank if isinstance(rank, int) else 10**8
            if rank < best_rank:
                best, best_rank = str(coin.get("id") or ""), rank
        return best

    async def daily(self, coin_id: str, *, days: int = 365) -> list[Bar]:
        """Daily bars from closes and volumes (CoinGecko's free daily data has
        no highs or lows, so each bar spans the move from the day before)."""
        body = await self._web.get_json(
            f"{API}/coins/{coin_id}/market_chart",
            params={"vs_currency": "usd", "days": days, "interval": "daily"},
            headers=self._headers(),
            what="CoinGecko",
        )
        return market_chart_bars(body)

    async def trending(self) -> list[str]:
        """Symbols of the coins people are searching for most."""
        body = await self._web.get_json(
            f"{API}/search/trending", headers=self._headers(), what="CoinGecko"
        )
        coins = body.get("coins") if isinstance(body, dict) else None
        found: list[str] = []
        for entry in coins if isinstance(coins, list) else []:
            item = entry.get("item") if isinstance(entry, dict) else None
            if isinstance(item, dict) and item.get("symbol"):
                found.append(str(item["symbol"]).upper())
        return found

    async def meme_movers(self, *, count: int = 25) -> list[dict[str, object]]:
        """The meme coins with the most trading, with their 24-hour moves."""
        body = await self._web.get_json(
            f"{API}/coins/markets",
            params={
                "vs_currency": "usd",
                "category": "meme-token",
                "order": "volume_desc",
                "per_page": count,
                "page": 1,
            },
            headers=self._headers(),
            what="CoinGecko",
        )
        return (
            [dict(row) for row in body if isinstance(row, dict)]
            if isinstance(body, list)
            else []
        )


def market_chart_bars(body: object) -> list[Bar]:
    prices = body.get("prices") if isinstance(body, dict) else None
    volumes = body.get("total_volumes") if isinstance(body, dict) else None
    volume_at: dict[int, float] = {}
    for row in volumes if isinstance(volumes, list) else []:
        if isinstance(row, list) and len(row) >= 2 and isinstance(row[1], int | float):
            volume_at[int(row[0]) // 86_400_000] = float(row[1])
    bars: list[Bar] = []
    previous: float | None = None
    seen: set[int] = set()
    for row in prices if isinstance(prices, list) else []:
        if not (isinstance(row, list) and len(row) >= 2):
            continue
        stamp, price = row[0], row[1]
        if not isinstance(stamp, int | float) or not isinstance(price, int | float):
            continue
        day = int(stamp) // 86_400_000
        if day in seen:
            continue
        seen.add(day)
        close = float(price)
        opened = previous if previous is not None else close
        bars.append(
            Bar(
                t=day * 86_400,
                o=opened,
                h=max(opened, close),
                l=min(opened, close),
                c=close,
                v=volume_at.get(day, 0.0),
            )
        )
        previous = close
    return bars
