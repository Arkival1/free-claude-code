"""The platforms the Trading page offers, with where to get keys and how each
suits someone in Australia. Keys never need withdrawal rights: FCC only
trades."""

from .alpaca import AlpacaBroker
from .btcmarkets import BtcMarketsBroker
from .coinbase import CoinbaseBroker
from .coinspot import CoinSpotBroker
from .ibkr import IbkrBroker
from .independent_reserve import IndependentReserveBroker
from .kraken import KrakenBroker
from .registry import BROKERS, BrokerSpec, KeyField, register
from .swyftx import SwyftxBroker
from .webhook import WebhookBroker

NO_WITHDRAWALS = " Never give the key withdrawal or transfer rights: FCC only trades."

PLATFORMS: tuple[BrokerSpec, ...] = (
    BrokerSpec(
        id="alpaca",
        name="Alpaca",
        markets=("us", "crypto"),
        what="US shares, ETFs, and crypto. Free paper (practice) account; stops "
        "and targets for whole shares sit on Alpaca's servers.",
        get_keys="alpaca.markets: sign up, open Paper Trading, and generate API "
        "keys there (live keys come from a live account)." + NO_WITHDRAWALS,
        australia="Paper accounts work from anywhere. Live accounts are open to "
        "many non-US residents: check Australia at sign-up. Trades in USD.",
        fields=(
            KeyField("key_id", "API key ID"),
            KeyField("secret", "Secret key"),
            KeyField(
                "account",
                "Account",
                secret=False,
                choices=("paper", "live"),
                placeholder="paper",
            ),
        ),
        factory=AlpacaBroker,
    ),
    BrokerSpec(
        id="ibkr",
        name="Interactive Brokers",
        markets=("asx", "us"),
        what="ASX and US shares from one account, through IBKR's Client Portal "
        "Gateway running on this PC.",
        get_keys="Download the Client Portal Gateway from Interactive Brokers "
        "(API section), run bin\\run.bat root\\conf.yaml, and log in at "
        "https://localhost:5000. No keys are stored in FCC.",
        australia="IBKR Australia: the ASX and US markets in one AUD account. "
        "Whole shares; a first ASX parcel must be worth $500.",
        fields=(
            KeyField(
                "gateway",
                "Gateway address",
                secret=False,
                placeholder="https://localhost:5000",
            ),
            KeyField("account", "Account (U...)", secret=False, optional=True),
        ),
        factory=IbkrBroker,
    ),
    BrokerSpec(
        id="kraken",
        name="Kraken",
        markets=("crypto",),
        what="Crypto, meme coins included, in AUD where Kraken has the pair "
        "(USD otherwise).",
        get_keys="kraken.com: Settings, API, create a key with Query Funds, "
        "Query Open and Closed Orders, Create & Modify Orders, and Cancel "
        "Orders." + NO_WITHDRAWALS,
        australia="Available in Australia; majors trade in AUD, most meme coins in USD.",
        fields=(
            KeyField("api_key", "API key"),
            KeyField("api_secret", "Private key"),
            KeyField(
                "quote",
                "Trade in",
                secret=False,
                choices=("AUD", "USD"),
                placeholder="AUD",
                optional=True,
            ),
        ),
        factory=KrakenBroker,
    ),
    BrokerSpec(
        id="coinbase",
        name="Coinbase",
        markets=("crypto",),
        what="Crypto on Coinbase Advanced Trade with a Developer Platform API key.",
        get_keys="Coinbase Developer Platform: API keys, create a secret key with "
        "trade permission (ECDSA works best); paste its name and private key."
        + NO_WITHDRAWALS,
        australia="Serves Australia; Advanced Trade pairs are mostly in USD or USDC.",
        fields=(
            KeyField(
                "key_name", "API key name", placeholder="organizations/.../apiKeys/..."
            ),
            KeyField("private_key", "Private key"),
            KeyField(
                "quote",
                "Trade in",
                secret=False,
                choices=("USD", "USDC"),
                placeholder="USD",
                optional=True,
            ),
        ),
        factory=CoinbaseBroker,
    ),
    BrokerSpec(
        id="btcmarkets",
        name="BTC Markets",
        markets=("crypto",),
        what="An Australian exchange: coins in AUD.",
        get_keys="btcmarkets.net: Account, API keys, create one with trade "
        "permission." + NO_WITHDRAWALS,
        australia="Australian, AUSTRAC-registered; every market is in AUD.",
        fields=(KeyField("api_key", "API key"), KeyField("api_secret", "Private key")),
        factory=BtcMarketsBroker,
    ),
    BrokerSpec(
        id="independentreserve",
        name="Independent Reserve",
        markets=("crypto",),
        what="An Australian exchange: coins in AUD.",
        get_keys="independentreserve.com: Settings, API keys, create one with "
        "read and trade access." + NO_WITHDRAWALS,
        australia="Australian exchange; markets in AUD.",
        fields=(KeyField("api_key", "API key"), KeyField("api_secret", "API secret")),
        factory=IndependentReserveBroker,
    ),
    BrokerSpec(
        id="coinspot",
        name="CoinSpot (beta)",
        markets=("crypto",),
        what="Australia's biggest coin list, hundreds of meme coins, in AUD. "
        "Beta: start with a small order.",
        get_keys="coinspot.com.au: My Account, API keys, create a full-access "
        "(trading) key." + NO_WITHDRAWALS,
        australia="Australian exchange; buys and sells instantly in AUD.",
        fields=(
            KeyField("api_key", "API key"),
            KeyField("api_secret", "API secret"),
            KeyField(
                "slippage_pct",
                "Price threshold (%)",
                secret=False,
                placeholder="1",
                optional=True,
            ),
        ),
        factory=CoinSpotBroker,
    ),
    BrokerSpec(
        id="swyftx",
        name="Swyftx (beta)",
        markets=("crypto",),
        what="An Australian exchange in AUD with a demo mode. Beta: practise in "
        "the demo environment first.",
        get_keys="swyftx.com.au: Profile, API keys, create a key with trading "
        "scope." + NO_WITHDRAWALS,
        australia="Australian exchange; the demo environment uses practice funds.",
        fields=(
            KeyField("api_key", "API key"),
            KeyField(
                "environment",
                "Environment",
                secret=False,
                choices=("demo", "live"),
                placeholder="demo",
            ),
        ),
        factory=SwyftxBroker,
    ),
    BrokerSpec(
        id="webhook",
        name="Any platform (webhook)",
        markets=("asx", "us", "crypto"),
        what="Posts each approved order as JSON to a URL: TradersPost, your own "
        "bot, a Discord or Slack channel, an automation tool.",
        get_keys="Paste the signal URL your platform or bot gives you. Optional: "
        "a secret (sent in a header and used to sign the body), a JSON template, "
        "and an account URL for the balance check.",
        australia="Works with anything that takes a web signal. FCC keeps the "
        "positions itself, since a webhook can't report fills.",
        fields=(
            KeyField("url", "Webhook URL", secret=False, placeholder="https://..."),
            KeyField("secret", "Secret", optional=True),
            KeyField(
                "header",
                "Secret header",
                secret=False,
                optional=True,
                placeholder="Authorization",
            ),
            KeyField(
                "account_size",
                "Account size",
                secret=False,
                optional=True,
                placeholder="5000",
            ),
            KeyField(
                "currency",
                "Account currency",
                secret=False,
                choices=("AUD", "USD"),
                optional=True,
                placeholder="AUD",
            ),
            KeyField(
                "account_url", "Account URL (optional)", secret=False, optional=True
            ),
            KeyField(
                "equity_path",
                "Equity field",
                secret=False,
                optional=True,
                placeholder="equity",
            ),
            KeyField(
                "cash_path",
                "Cash field",
                secret=False,
                optional=True,
                placeholder="cash",
            ),
            KeyField(
                "template", "JSON template (optional)", secret=False, optional=True
            ),
        ),
        factory=WebhookBroker,
    ),
)


def ensure_catalog() -> None:
    """Make every platform available (safe to call more than once)."""
    for spec in PLATFORMS:
        if spec.id not in BROKERS:
            register(spec)
