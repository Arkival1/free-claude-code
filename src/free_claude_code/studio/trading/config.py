"""The trading desk's settings, kept in one JSON file next to Studio's data.

Every number has a floor and a ceiling, so a typo can't set a 500% position.
Broker keys are not here: they live in their own owner-only file.
"""

import json
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .records import TradeMode

type Depth = Literal["fast", "balanced", "max"]
type Grade = Literal["A", "B", "C", "D", "E", "F"]
GRADES: tuple[str, ...] = ("A", "B", "C", "D", "E", "F")

REBUTTAL_ROUNDS: dict[str, int] = {"fast": 1, "balanced": 2, "max": 4}
"""The most rebuttal rounds each prediction depth allows."""
OPENING_SAMPLES: dict[str, int] = {"fast": 1, "balanced": 1, "max": 3}
"""How many times each analyst's opening is asked and averaged."""

LIVE_AUTO_PHRASE = "I accept real-money trades"
"""What the owner types, on the PC, to let live orders go without a tap."""


class SeatConfig(BaseModel):
    """One of the five seats and the model it thinks with."""

    model_config = ConfigDict(extra="ignore")

    seat: int = Field(ge=1, le=5)
    name: str = Field(min_length=1, max_length=40)
    model: str = Field(default="", max_length=300)
    """Empty: Studio's server model (or the PC's model when it has no key)."""
    temperature: float = Field(default=0.3, ge=0.0, le=1.5)
    on: bool = True


DEFAULT_SEATS: tuple[SeatConfig, ...] = (
    SeatConfig(seat=1, name="Technical Analyst"),
    SeatConfig(seat=2, name="Researcher"),
    SeatConfig(seat=3, name="Macro & Sentiment"),
    SeatConfig(seat=4, name="Risk Guardian", temperature=0.2),
    SeatConfig(seat=5, name="Portfolio Manager", temperature=0.2),
)


class RiskLimits(BaseModel):
    """Hard rules: plain code checks these, and no model can talk past them."""

    model_config = ConfigDict(extra="ignore")

    risk_per_trade_pct: float = Field(default=1.0, ge=0.1, le=5.0)
    """Equity lost if the stop is hit, in percent."""
    max_position_pct: float = Field(default=10.0, ge=1.0, le=50.0)
    max_order_value: float = Field(default=1000.0, ge=10.0, le=1_000_000.0)
    """In the base currency."""
    max_open_positions: int = Field(default=5, ge=1, le=50)
    max_trades_per_day: int = Field(default=6, ge=1, le=100)
    max_daily_loss_pct: float = Field(default=3.0, ge=0.5, le=20.0)
    min_confidence: float = Field(default=0.6, ge=0.3, le=0.95)
    min_consensus: float = Field(default=0.55, ge=0.5, le=0.9)
    """The weighted chance of a rise the seats must end on to buy."""
    require_stop: bool = True
    cooldown_minutes: int = Field(default=60, ge=0, le=10_080)
    """Wait this long before trading the same symbol again."""
    slippage_pct: float = Field(default=1.0, ge=0.1, le=10.0)
    """How far the live price may sit from the decision's price."""
    meme_position_pct: float = Field(default=1.0, ge=0.1, le=10.0)
    meme_total_pct: float = Field(default=5.0, ge=0.5, le=25.0)
    meme_min_liquidity_usd: float = Field(default=250_000.0, ge=10_000.0)
    meme_min_age_days: int = Field(default=14, ge=0, le=3650)
    allow: list[str] = Field(default_factory=list, max_length=500)
    """When set, only these symbols trade."""
    deny: list[str] = Field(default_factory=list, max_length=500)

    @field_validator("allow", "deny", mode="before")
    @classmethod
    def _symbols(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.replace(",", " ").split()
        if isinstance(value, list):
            return [str(item).strip().upper() for item in value if str(item).strip()]
        return value


class AssessmentLimits(BaseModel):
    """The risk assessment period before every order."""

    model_config = ConfigDict(extra="ignore")

    min_grade: Grade = "C"
    min_reward_risk: float = Field(default=1.5, ge=0.5, le=10.0)
    require_positive_ev: bool = True
    max_correlation: float = Field(default=0.8, ge=0.3, le=1.0)
    max_adv_pct: float = Field(default=1.0, ge=0.01, le=25.0)
    """The order may be at most this share of a day's trading."""
    earnings_blackout_days: int = Field(default=2, ge=0, le=30)
    cooling_stocks_minutes: float = Field(default=2.0, ge=0.0, le=15.0)
    cooling_crypto_minutes: float = Field(default=1.0, ge=0.0, le=15.0)
    entry_band_pct: float = Field(default=1.0, ge=0.1, le=10.0)
    """How far the price may move during the cooling-off wait."""
    atr_spike_pct: float = Field(default=50.0, ge=10.0, le=500.0)
    """A jump in volatility (ATR %) this big during the wait aborts the trade."""


class DeskConfig(BaseModel):
    """Everything the owner sets on the Trading page."""

    model_config = ConfigDict(extra="ignore")

    mode: TradeMode = "paper"
    broker: str = Field(default="paper", max_length=40)
    currency: Literal["AUD", "USD"] = "AUD"
    paper_cash: float = Field(default=10_000.0, ge=100.0, le=10_000_000.0)
    markets: dict[str, bool] = Field(
        default_factory=lambda: {"us": True, "asx": True, "crypto": True, "meme": True}
    )
    watchlist: list[str] = Field(default_factory=list, max_length=200)
    scan_minutes: int = Field(default=15, ge=5, le=1440)
    candidates: int = Field(default=2, ge=1, le=5)
    depth: Depth = "balanced"
    seats: list[SeatConfig] = Field(default_factory=lambda: list(DEFAULT_SEATS))
    risk: RiskLimits = Field(default_factory=RiskLimits)
    assessment: AssessmentLimits = Field(default_factory=AssessmentLimits)
    approval_minutes: int = Field(default=10, ge=1, le=1440)
    crypto_debrief_hour_utc: int = Field(default=14, ge=0, le=23)
    """When the crypto session debrief runs (14:00 UTC is midnight in Sydney)."""
    fee_pct: float = Field(default=0.1, ge=0.0, le=2.0)
    """The paper account's fee per trade, in percent."""
    min_fee: float = Field(default=1.0, ge=0.0, le=50.0)
    live_auto_confirmed_at: int = 0
    accounts: dict[str, str] = Field(default_factory=dict)
    """The account each live platform was verified as: broker → fingerprint."""
    running: bool = False

    @field_validator("watchlist", mode="before")
    @classmethod
    def _watchlist(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.replace(",", " ").split()
        if isinstance(value, list):
            seen: dict[str, None] = {}
            for item in value:
                text = str(item).strip()
                if text:
                    seen.setdefault(text.upper(), None)
            return list(seen)
        return value

    @field_validator("seats")
    @classmethod
    def _five_seats(cls, value: list[SeatConfig]) -> list[SeatConfig]:
        by_seat = {seat.seat: seat for seat in value}
        seats = [by_seat.get(default.seat, default) for default in DEFAULT_SEATS]
        # The Risk Guardian and the Portfolio Manager are never switched off.
        return [
            seat.model_copy(update={"on": True}) if seat.seat >= 4 else seat
            for seat in seats
        ]

    def seat(self, number: int) -> SeatConfig:
        return next(seat for seat in self.seats if seat.seat == number)

    @property
    def live(self) -> bool:
        return self.mode != "paper"


class DeskConfigStore:
    """Reads and writes desk.json atomically; a broken file means defaults."""

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> DeskConfig:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError, ValueError:
            return DeskConfig()
        try:
            return DeskConfig.model_validate(raw if isinstance(raw, dict) else {})
        except ValidationError:
            return DeskConfig()

    def save(self, config: DeskConfig) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(".tmp")
        temporary.write_text(config.model_dump_json(indent=1), encoding="utf-8")
        os.replace(temporary, self._path)
