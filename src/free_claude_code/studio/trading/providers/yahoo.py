"""Yahoo Finance's chart API: US and ASX shares, indices, currencies, coins.

No key is needed. It is unofficial, so every answer is checked and anything
odd becomes a clear error the desk can fall back from.
"""

from collections.abc import Sequence

from ...resilience import ServiceError, Web
from ..indicators import Bar

HOSTS = ("https://query1.finance.yahoo.com", "https://query2.finance.yahoo.com")
BROWSER = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
"""Yahoo turns away requests that don't look like a browser's."""

RANGES: dict[str, str] = {"1d": "2y", "1h": "60d", "15m": "5d", "1m": "1d"}


class YahooChart:
    def __init__(self, web: Web) -> None:
        self._web = web

    async def chart(
        self, symbol: str, interval: str
    ) -> tuple[list[Bar], dict[str, object]]:
        """Bars for one symbol at one interval, and the chart's meta block."""
        last: ServiceError | None = None
        for host in HOSTS:
            try:
                body = await self._web.get_json(
                    f"{host}/v8/finance/chart/{symbol}",
                    params={
                        "range": RANGES.get(interval, "6mo"),
                        "interval": interval,
                        "includePrePost": False,
                    },
                    headers={"user-agent": BROWSER, "accept": "application/json"},
                    what="Yahoo Finance",
                )
            except ServiceError as error:
                last = error
                if error.status in {400, 404}:
                    break
                continue
            return parse_chart(body, symbol)
        raise last or ServiceError(f"Yahoo Finance had no chart for {symbol}.")


def parse_chart(body: object, symbol: str) -> tuple[list[Bar], dict[str, object]]:
    """Bars and meta from a chart answer; missing candles are skipped."""
    chart = body.get("chart") if isinstance(body, dict) else None
    results = chart.get("result") if isinstance(chart, dict) else None
    if not isinstance(results, list) or not results or not isinstance(results[0], dict):
        error = chart.get("error") if isinstance(chart, dict) else None
        detail = error.get("description") if isinstance(error, dict) else ""
        raise ServiceError(
            f"Yahoo Finance had no chart for {symbol}"
            + (f": {detail}" if detail else "."),
            status=404,
        )
    result = results[0]
    meta = result.get("meta") if isinstance(result.get("meta"), dict) else {}
    stamps = result.get("timestamp") or []
    indicators = result.get("indicators")
    quotes = indicators.get("quote") if isinstance(indicators, dict) else None
    quote = quotes[0] if isinstance(quotes, list) and quotes else {}
    if not isinstance(stamps, list) or not isinstance(quote, dict):
        return [], dict(meta) if isinstance(meta, dict) else {}
    columns = [
        _column(quote.get(name), len(stamps))
        for name in ("open", "high", "low", "close", "volume")
    ]
    bars: list[Bar] = []
    for index, stamp in enumerate(stamps):
        o, h, low, c, v = (column[index] for column in columns)
        if c is None or not isinstance(stamp, int | float):
            continue
        bars.append(
            Bar(
                t=int(stamp),
                o=o if o is not None else c,
                h=max(value for value in (h, o, c) if value is not None),
                l=min(value for value in (low, o, c) if value is not None),
                c=c,
                v=v or 0.0,
            )
        )
    return bars, dict(meta) if isinstance(meta, dict) else {}


def _column(values: object, size: int) -> list[float | None]:
    if not isinstance(values, Sequence) or isinstance(values, str):
        return [None] * size
    found: list[float | None] = [
        float(value) if isinstance(value, int | float) else None
        for value in list(values)[:size]
    ]
    return found + [None] * (size - len(found))
