"""What a symbol is: a US or ASX share, a crypto coin, or a token on a DEX.

People write symbols many ways (``BHP``, ``ASX:BHP``, ``bhp.ax``, ``BTC``,
``BTC-AUD``, ``sol:<address>``); they all end up as one ``Instrument`` with a
market and the currency its prices come in. DEX tokens are research only: no
supported platform can buy them without a wallet key, which FCC never holds.
"""

import re
from dataclasses import dataclass

from free_claude_code.core.json_types import JsonObject

COINGECKO_IDS: dict[str, str] = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "XRP": "ripple",
    "BNB": "binancecoin",
    "ADA": "cardano",
    "AVAX": "avalanche-2",
    "DOT": "polkadot",
    "LINK": "chainlink",
    "LTC": "litecoin",
    "BCH": "bitcoin-cash",
    "TRX": "tron",
    "XLM": "stellar",
    "ATOM": "cosmos",
    "NEAR": "near",
    "APT": "aptos",
    "ARB": "arbitrum",
    "OP": "optimism",
    "SUI": "sui",
    "TON": "the-open-network",
    "HBAR": "hedera-hashgraph",
    "UNI": "uniswap",
    "AAVE": "aave",
    "ETC": "ethereum-classic",
    "FIL": "filecoin",
    "ICP": "internet-computer",
    "INJ": "injective-protocol",
    "RENDER": "render-token",
    "DOGE": "dogecoin",
    "SHIB": "shiba-inu",
    "PEPE": "pepe",
    "BONK": "bonk",
    "WIF": "dogwifcoin",
    "FLOKI": "floki",
    "BRETT": "based-brett",
    "POPCAT": "popcat",
    "MOG": "mog-coin",
    "TURBO": "turbo",
    "PENGU": "pudgy-penguins",
    "FARTCOIN": "fartcoin",
    "TRUMP": "official-trump",
    "MEW": "cat-in-a-dogs-world",
    "BOME": "book-of-meme",
    "PNUT": "peanut-the-squirrel",
    "MOODENG": "moo-deng",
    "GOAT": "goatseus-maximus",
}
"""Coins whose CoinGecko id is known; others are looked up by name."""

MEME_COINS = frozenset(
    {
        "DOGE",
        "SHIB",
        "PEPE",
        "BONK",
        "WIF",
        "FLOKI",
        "BRETT",
        "POPCAT",
        "MOG",
        "TURBO",
        "PENGU",
        "FARTCOIN",
        "TRUMP",
        "MEW",
        "BOME",
        "PNUT",
        "MOODENG",
        "GOAT",
    }
)

ASX_DEFAULTS: tuple[str, ...] = tuple(
    f"{code}.AX"
    for code in (
        "BHP",
        "CBA",
        "CSL",
        "NAB",
        "WBC",
        "ANZ",
        "MQG",
        "WES",
        "FMG",
        "RIO",
        "WDS",
        "TLS",
        "WOW",
        "GMG",
        "TCL",
        "ALL",
        "STO",
        "COL",
        "REA",
        "XRO",
        "QBE",
        "SUN",
        "NST",
        "EVN",
        "PLS",
        "MIN",
        "WTC",
        "CPU",
        "ORG",
        "LYC",
    )
)
US_DEFAULTS: tuple[str, ...] = (
    "AAPL",
    "MSFT",
    "NVDA",
    "AMZN",
    "GOOGL",
    "META",
    "TSLA",
    "AVGO",
    "AMD",
    "NFLX",
    "JPM",
    "V",
    "MA",
    "COST",
    "LLY",
    "UNH",
    "XOM",
    "BAC",
    "WMT",
    "PLTR",
    "COIN",
    "MSTR",
    "ARM",
    "CRM",
    "ORCL",
    "ADBE",
    "QCOM",
    "MU",
    "SPY",
    "QQQ",
)
CRYPTO_DEFAULTS: tuple[str, ...] = (
    "BTC",
    "ETH",
    "SOL",
    "XRP",
    "BNB",
    "ADA",
    "AVAX",
    "LINK",
    "DOT",
    "LTC",
)
MEME_DEFAULTS: tuple[str, ...] = (
    "DOGE",
    "SHIB",
    "PEPE",
    "BONK",
    "WIF",
    "FLOKI",
)

INDEX_FOR_MARKET: dict[str, str] = {"asx": "^AXJO", "us": "^GSPC", "crypto": "BTC"}
"""The yardstick each market is read against for its regime and beta."""

_CHAINS = {"sol": "solana", "eth": "ethereum", "base": "base", "bsc": "bsc"}
_PAIR = re.compile(r"^([A-Z0-9]{2,15})[-/](USD|AUD|USDT|USDC)$")
_SHARE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


@dataclass(frozen=True, slots=True)
class Instrument:
    """One tradable (or researchable) thing and where its prices come from."""

    symbol: str
    market: str
    """us, asx, crypto, dex, or index."""
    currency: str
    """The currency its price data comes in."""
    meme: bool = False
    chain: str = ""
    address: str = ""

    @property
    def tradable(self) -> bool:
        return self.market in {"us", "asx", "crypto"}

    @property
    def code(self) -> str:
        """The symbol without its market suffix: BHP for BHP.AX."""
        return self.symbol.removesuffix(".AX")

    @property
    def yahoo(self) -> str:
        if self.market == "crypto":
            return f"{self.symbol}-USD"
        if self.market == "dex":
            return ""
        return self.symbol

    @property
    def coingecko(self) -> str:
        return COINGECKO_IDS.get(self.symbol, "") if self.market == "crypto" else ""

    @property
    def sector(self) -> str:
        """A rough grouping for exposure limits: the market, or meme coins."""
        return "meme" if self.meme else self.market

    def view(self) -> JsonObject:
        return {
            "symbol": self.symbol,
            "market": self.market,
            "currency": self.currency,
            "meme": self.meme,
            "tradable": self.tradable,
            "chain": self.chain,
            "address": self.address,
        }


class SymbolError(ValueError):
    """A symbol nobody could read."""


def parse_symbol(text: str) -> Instrument:
    """Read a symbol however it was written."""
    raw = text.strip()
    if not raw:
        raise SymbolError("Give a symbol, e.g. BHP.AX, AAPL, or BTC.")
    prefix, colon, rest = raw.partition(":")
    if colon and prefix.lower() in _CHAINS and len(rest.strip()) >= 20:
        address = rest.strip()
        return Instrument(
            symbol=f"{prefix.lower()}:{address}",
            market="dex",
            currency="USD",
            meme=True,
            chain=_CHAINS[prefix.lower()],
            address=address,
        )
    upper = raw.upper().replace(" ", "")
    if upper.startswith("^"):
        return Instrument(symbol=upper, market="index", currency="")
    if upper.startswith("ASX:"):
        upper = upper.removeprefix("ASX:") + ".AX"
    if upper.endswith(".AX"):
        code = upper.removesuffix(".AX")
        if not code or not _SHARE.match(code):
            raise SymbolError(f"{raw} isn't an ASX code.")
        return Instrument(symbol=upper, market="asx", currency="AUD")
    if upper.startswith("CRYPTO:"):
        return _coin(upper.removeprefix("CRYPTO:"))
    pair = _PAIR.match(upper)
    if pair:
        return _coin(pair.group(1))
    if upper in COINGECKO_IDS:
        return _coin(upper)
    for market in ("US:", "NYSE:", "NASDAQ:"):
        upper = upper.removeprefix(market)
    if _SHARE.match(upper):
        return Instrument(symbol=upper, market="us", currency="USD")
    raise SymbolError(f"{raw} doesn't look like a share, a coin, or a token.")


def _coin(code: str) -> Instrument:
    if not re.match(r"^[A-Z0-9]{2,15}$", code):
        raise SymbolError(f"{code} isn't a coin symbol.")
    return Instrument(
        symbol=code, market="crypto", currency="USD", meme=code in MEME_COINS
    )


def universe(markets: dict[str, bool], watchlist: list[str]) -> list[Instrument]:
    """Everything the scanner looks at: the watchlist first, then each market's
    default list, without repeats."""
    chosen: dict[str, Instrument] = {}
    for text in watchlist:
        try:
            found = parse_symbol(text)
        except SymbolError:
            continue
        if _enabled(found, markets):
            chosen.setdefault(found.symbol, found)
    for market, defaults in (
        ("asx", ASX_DEFAULTS),
        ("us", US_DEFAULTS),
        ("crypto", CRYPTO_DEFAULTS),
        ("meme", MEME_DEFAULTS),
    ):
        if not markets.get(market):
            continue
        for text in defaults:
            found = parse_symbol(text)
            chosen.setdefault(found.symbol, found)
    return list(chosen.values())


def _enabled(found: Instrument, markets: dict[str, bool]) -> bool:
    if found.meme:
        return bool(markets.get("meme"))
    if found.market == "dex":
        return bool(markets.get("meme"))
    return bool(markets.get(found.market))
