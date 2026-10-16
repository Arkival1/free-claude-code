"""The risk assessment period: nothing is ordered until it passes.

After the debate decides to buy, plain code writes a risk report:
- what's at risk in the base currency, the reward for that risk, and the
  expected value from the seats' own forecasts blended with the base rates;
- a quarter-Kelly ceiling on the size, the stop's distance in ATRs (a stop
  inside normal noise gets hit by noise), and the order's share of a day's
  volume;
- exposure after the trade, correlation with what's already held, and the
  currency risk of a US asset in an Australian account;
- stress tests: sharp drops, a gap through the stop overnight, the index
  falling 3% (scaled by beta), and for meme coins a 30% flash crash;
- earnings and macro events inside the holding window.
Then all five seats look at the report: the analysts from their angles, the
Risk Guardian grades it A to F with conditions, and the Portfolio Manager may
only keep the size, shrink it, or defer. The worse of the code's grade and
the Guardian's must meet the owner's minimum. Last, a cooling-off wait: the
desk waits a minute or two, then re-checks the price, the volatility, and
the headlines before the order goes on to the hard limits and the account
check.
"""

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from free_claude_code.core.json_types import JsonObject

from ..llm import StudioLLMError
from .briefing import Briefing
from .brokers.base import Rules
from .config import DeskConfig
from .data import Quote
from .indicators import Bar, closes, correlation, returns
from .log import SEAT_NAMES, Feed
from .risk import Exposure, Sizing
from .seats import Decision, Event, Forecast, RiskNote, Think, ask_json

GRADES = "ABCDEF"
NOTE_KEYS = '"concerns": ["..."], "conditions": ["..."], "note": "..."'
GUARDIAN_KEYS = '"grade": "A|B|C|D|E|F", ' + NOTE_KEYS
PM_KEYS = '"size_factor": 0-1 (1 keeps the size; you may not raise it), "defer": true|false, "note": "..."'
SPREAD_LIMIT_PCT = {"crypto": 2.0}
"""Wider than this between bid and ask at the end of the wait aborts (1% for shares)."""


def worse(a: str, b: str) -> str:
    """The worse of two grades (an empty grade doesn't count)."""
    known = [grade for grade in (a, b) if grade in GRADES]
    return max(known, key=GRADES.index) if known else "C"


@dataclass(frozen=True, slots=True)
class StressCase:
    name: str
    loss: float
    """In the base currency."""
    pct_of_equity: float


@dataclass(slots=True)
class RiskAssessment:
    symbol: str
    entry: float
    stop: float
    target: float
    qty: float
    value: float
    at_risk: float
    at_risk_pct: float
    reward_risk: float | None
    p_target: float | None
    ev: float | None
    ev_pct: float | None
    kelly: float | None
    stop_atr: float | None
    adv_pct: float | None
    exposure_pct: dict[str, float]
    correlations: dict[str, float]
    stress: list[StressCase]
    events: list[JsonObject]
    meme_warnings: list[str]
    fx_note: str
    code_grade: str
    guardian_grade: str = ""
    grade: str = "C"
    notes: dict[int, RiskNote] = field(default_factory=dict)
    blockers: list[str] = field(default_factory=list)
    cautions: list[str] = field(default_factory=list)
    conditions: list[str] = field(default_factory=list)
    size_factor: float = 1.0
    deferred: bool = False
    cooling_minutes: float = 0.0
    atr_pct: float | None = None
    titles: list[str] = field(default_factory=list)
    bound_by: str = ""

    @property
    def passed(self) -> bool:
        return not self.blockers and not self.deferred and self.qty > 0

    def view(self) -> JsonObject:
        return {
            "symbol": self.symbol,
            "entry": self.entry,
            "stop": self.stop,
            "target": self.target,
            "qty": self.qty,
            "value": round(self.value, 2),
            "at_risk": round(self.at_risk, 2),
            "at_risk_pct": round(self.at_risk_pct, 3),
            "reward_risk": _r(self.reward_risk, 2),
            "p_target": _r(self.p_target, 3),
            "ev": _r(self.ev, 2),
            "ev_pct": _r(self.ev_pct, 2),
            "kelly": _r(self.kelly, 3),
            "stop_atr": _r(self.stop_atr, 2),
            "adv_pct": _r(self.adv_pct, 3),
            "exposure_pct": {k: round(v, 2) for k, v in self.exposure_pct.items()},
            "correlations": {k: round(v, 2) for k, v in self.correlations.items()},
            "stress": [
                {
                    "name": case.name,
                    "loss": round(case.loss, 2),
                    "pct_of_equity": round(case.pct_of_equity, 2),
                }
                for case in self.stress
            ],
            "events": self.events,
            "meme_warnings": self.meme_warnings,
            "fx_note": self.fx_note,
            "code_grade": self.code_grade,
            "guardian_grade": self.guardian_grade,
            "grade": self.grade,
            "notes": {
                str(seat): note.model_dump() for seat, note in self.notes.items()
            },
            "blockers": self.blockers,
            "cautions": self.cautions,
            "conditions": self.conditions,
            "size_factor": self.size_factor,
            "deferred": self.deferred,
            "passed": self.passed,
            "cooling_minutes": self.cooling_minutes,
            "atr_pct": _r(self.atr_pct, 3),
            "bound_by": self.bound_by,
        }

    def report(self, currency: str) -> str:
        """The report as lines for the seats' risk round."""
        worst = max(self.stress, key=lambda case: case.loss, default=None)
        rows = [
            f"ORDER UNDER REVIEW: buy {self.qty:g} {self.symbol} near {self.entry:g} "
            f"({self.value:,.2f} {currency}); stop {self.stop:g} "
            f"({(self.stop / self.entry - 1) * 100:+.1f}%), target {self.target:g} "
            f"({(self.target / self.entry - 1) * 100:+.1f}%).",
            f"At risk {self.at_risk:,.2f} {currency} ({self.at_risk_pct:.2f}% of equity); "
            f"reward for risk {_show(self.reward_risk, 'x')}; chance the target comes "
            f"first {_show(self.p_target, '%')}; expected value "
            f"{_show(self.ev, f' {currency}')} ({_show(self.ev_pct, '%')} of the order).",
            f"Stop is {_show(self.stop_atr, ' ATR')} away; the order is "
            f"{_show(self.adv_pct, '%')} of a day's volume; quarter-Kelly "
            f"{_show(self.kelly, '%')}.",
        ]
        if self.correlations:
            rows.append(
                "Correlation with holdings: "
                + ", ".join(f"{k} {v:+.2f}" for k, v in self.correlations.items())
            )
        if self.exposure_pct:
            rows.append(
                "Exposure after: "
                + ", ".join(f"{k} {v:.1f}%" for k, v in self.exposure_pct.items())
            )
        if worst is not None:
            rows.append(
                "Stress: "
                + "; ".join(
                    f"{case.name} -{case.loss:,.0f} ({case.pct_of_equity:.2f}%)"
                    for case in self.stress
                )
            )
        if self.events:
            rows.append(
                "Events: "
                + "; ".join(
                    f"{event['name']} {event['date'] or 'date unknown'}"
                    for event in self.events
                )
            )
        if self.meme_warnings:
            rows.append("Meme-coin warnings: " + ", ".join(self.meme_warnings))
        if self.fx_note:
            rows.append(self.fx_note)
        if self.blockers or self.cautions:
            rows.append(
                "The code's own findings: "
                + "; ".join([*self.blockers, *self.cautions])
                + f" (code grade {self.code_grade})"
            )
        return "\n".join(rows)


def _r(value: float | None, digits: int) -> float | None:
    return round(value, digits) if value is not None else None


def _show(value: float | None, unit: str) -> str:
    if value is None:
        return "unknown"
    if unit == "%":
        return f"{value * 100:.0f}%" if abs(value) <= 1.0 else f"{value:.1f}%"
    if unit == "x":
        return f"{value:.2f} to 1"
    return f"{value:,.2f}{unit}"


def _blend(
    decision: Decision,
    closing: Mapping[int, Forecast],
    weights: Mapping[int, float],
    base_target_first: float | None,
) -> float | None:
    """The chance the target comes first: the Portfolio Manager's, the seats'
    (weighted by track record), and the base rate, averaged."""
    found: list[float] = []
    if decision.p_target is not None:
        found.append(decision.p_target)
    seats = {
        seat: view.p_target
        for seat, view in closing.items()
        if view.p_target is not None
    }
    if seats:
        total = sum(weights.get(seat, 1.0) for seat in seats)
        found.append(
            sum(
                weights.get(seat, 1.0) * p for seat, p in seats.items() if p is not None
            )
            / total
        )
    if base_target_first is not None:
        found.append(base_target_first)
    return sum(found) / len(found) if found else None


def _days_until(day: str, today: date) -> int | None:
    try:
        return (date.fromisoformat(day) - today).days
    except ValueError:
        return None


@dataclass(frozen=True, slots=True)
class Holdings:
    """What the account holds, for exposure and correlation."""

    equity: float
    positions: Sequence[Exposure]
    bars: Mapping[str, Sequence[Bar]]
    sectors: Mapping[str, str]


def risk_report(
    *,
    decision: Decision,
    briefing: Briefing,
    sizing: Sizing,
    rules: Rules | None,
    holdings: Holdings,
    closing: Mapping[int, Forecast],
    weights: Mapping[int, float],
    fx: float,
    config: DeskConfig,
    earnings: str,
    events: Sequence[Event],
    now_ms: int,
) -> RiskAssessment:
    """The code's half of the risk assessment: numbers, stress, events."""
    price = briefing.price
    entry = (
        decision.limit_price
        if decision.order_type == "limit" and decision.limit_price
        else price
    )
    stop = decision.stop_loss or 0.0
    atr_value = briefing.tech.atr or 0.0
    target = decision.take_profit or entry + 2 * atr_value
    unit_risk = max(0.0, (entry - stop) * fx)
    unit_reward = max(0.0, (target - entry) * fx)
    costs = entry * fx * (2 * config.fee_pct / 100 + 0.001)
    p_target = _blend(
        decision,
        closing,
        weights,
        briefing.base.target_first if briefing.base is not None else None,
    )
    reward_risk = unit_reward / unit_risk if unit_risk > 0 else None
    kelly = None
    qty = sizing.qty
    if p_target is not None and reward_risk:
        kelly = max(0.0, (p_target - (1 - p_target) / reward_risk) / 4)
        if unit_risk > 0 and holdings.equity > 0:
            kelly_qty = holdings.equity * kelly / unit_risk
            qty = min(qty, kelly_qty)
    if rules is not None:
        qty = rules.fit(qty)
    value = qty * entry * fx
    at_risk = qty * unit_risk
    ev = (
        qty * (p_target * unit_reward - (1 - p_target) * unit_risk - costs)
        if p_target is not None
        else None
    )
    equity = holdings.equity
    blockers: list[str] = []
    cautions: list[str] = []
    limits = config.assessment
    grade = "A"

    def lower(to: str, why: str, *, block: bool = False) -> None:
        nonlocal grade
        grade = worse(grade, to)
        (blockers if block else cautions).append(why)

    if qty <= 0:
        lower("F", f"No size is left after the limits ({sizing.bound_by}).", block=True)
    if ev is not None and ev <= 0:
        lower(
            "D", "The expected value is not positive.", block=limits.require_positive_ev
        )
    if p_target is None:
        lower("C", "No usable chance of the target coming first.")
    if reward_risk is not None and reward_risk < limits.min_reward_risk:
        lower(
            "D",
            f"Reward for risk {reward_risk:.2f} is under the {limits.min_reward_risk:g} minimum.",
            block=True,
        )
    stop_atr = (entry - stop) / atr_value if atr_value > 0 else None
    if stop_atr is not None and stop_atr < 0.5:
        lower(
            "C", f"The stop is only {stop_atr:.2f} ATR away: normal noise could hit it."
        )
    if briefing.tech.avg_volume and qty > 0:
        adv_pct = qty / briefing.tech.avg_volume * 100
        if briefing.instrument.market == "crypto":
            # A coin's daily volume is in dollars, so the order's value is the
            # fair comparison; the larger figure is kept so this check can
            # only get stricter than it was.
            adv_pct = max(adv_pct, qty * entry / briefing.tech.avg_volume * 100)
        if adv_pct > limits.max_adv_pct:
            lower(
                "D",
                f"The order is {adv_pct:.2f}% of a day's volume (limit {limits.max_adv_pct:g}%).",
                block=True,
            )
    else:
        adv_pct = None
    exposure: dict[str, float] = {}
    if equity > 0:
        for item in holdings.positions:
            sector = holdings.sectors.get(item.symbol, "other")
            exposure[sector] = exposure.get(sector, 0.0) + item.value / equity * 100
        mine = briefing.instrument.sector
        exposure[mine] = exposure.get(mine, 0.0) + value / equity * 100
    correlations: dict[str, float] = {}
    mine_returns = returns(closes(briefing.daily[-61:]))
    for symbol, bars in holdings.bars.items():
        if symbol == briefing.symbol or len(bars) < 20:
            continue
        found = correlation(mine_returns, returns(closes(bars[-61:])))
        if found is not None:
            correlations[symbol] = found
            if found > limits.max_correlation:
                lower(
                    "C",
                    f"Moves with {symbol} (correlation {found:.2f}, limit "
                    f"{limits.max_correlation:g}).",
                    block=True,
                )
    stress: list[StressCase] = []
    if qty > 0 and equity > 0:
        unit = qty * fx

        def case(name: str, loss: float) -> None:
            stress.append(
                StressCase(name, max(0.0, loss), max(0.0, loss) / equity * 100)
            )

        for move in (1, 2, 3):
            if atr_value:
                case(f"{move} ATR drop", unit * atr_value * move)
        if briefing.instrument.market in {"us", "asx"}:
            case(
                "Gap through the stop overnight",
                unit * (entry - (stop - atr_value)) * 1.002,
            )
        else:
            crash = 0.30 if briefing.instrument.meme else 0.15
            case(f"{crash:.0%} flash crash", value * crash)
        market_beta = briefing.beta if briefing.beta is not None else 1.0
        case("Index falls 3%", value * 0.03 * max(0.0, market_beta))
        worst = max(stress, key=lambda item: item.loss)
        if worst.pct_of_equity > 3.0:
            lower(
                "C",
                f"The worst stress case ({worst.name}) would cost "
                f"{worst.pct_of_equity:.1f}% of the account.",
            )
    today = datetime.fromtimestamp(now_ms / 1000, tz=UTC).date()
    window = (
        decision.horizon_days
        if briefing.instrument.market in {"crypto", "dex"}
        else int(decision.horizon_days * 7 / 5) + 1
    )
    checked: list[JsonObject] = []
    if briefing.instrument.market in {"us", "asx"}:
        days = _days_until(earnings, today) if earnings else None
        checked.append(
            {
                "name": "Earnings or results",
                "date": earnings,
                "days_away": days,
                "in_window": days is not None and 0 <= days <= window,
            }
        )
        if days is None:
            lower("C", "The next earnings or results date isn't known.")
        elif 0 <= days <= limits.earnings_blackout_days:
            lower(
                "E",
                f"Earnings or results in {days} days (blackout {limits.earnings_blackout_days}).",
                block=True,
            )
        elif 0 <= days <= window:
            lower(
                "C", f"Earnings or results in {days} days, inside the holding window."
            )
    for event in events:
        days = _days_until(event.date, today) if event.date else None
        in_window = days is not None and 0 <= days <= window
        checked.append(
            {
                "name": event.name,
                "date": event.date,
                "days_away": days,
                "in_window": in_window,
            }
        )
        if in_window:
            lower("B", f"{event.name} on {event.date} falls inside the holding window.")
    warnings = list(briefing.meme_warnings)
    if warnings:
        lower(
            "D" if len(warnings) > 1 else "C",
            "Meme-coin warning signs: " + ", ".join(warnings),
        )
    fx_note = ""
    if briefing.quote.currency != config.currency:
        fx_note = (
            f"Priced in {briefing.quote.currency}: a move in the "
            f"{config.currency}/{briefing.quote.currency} rate changes the result too."
        )
    return RiskAssessment(
        symbol=briefing.symbol,
        entry=entry,
        stop=stop,
        target=target,
        qty=qty,
        value=value,
        at_risk=at_risk,
        at_risk_pct=at_risk / equity * 100 if equity > 0 else 0.0,
        reward_risk=reward_risk,
        p_target=p_target,
        ev=ev,
        ev_pct=ev / value * 100 if ev is not None and value > 0 else None,
        kelly=kelly,
        stop_atr=stop_atr,
        adv_pct=adv_pct,
        exposure_pct=exposure,
        correlations=correlations,
        stress=stress,
        events=checked,
        meme_warnings=warnings,
        fx_note=fx_note,
        code_grade=grade,
        grade=grade,
        blockers=blockers,
        cautions=cautions,
        atr_pct=briefing.tech.atr_pct,
        titles=sorted(briefing.research.titles()),
        bound_by=sizing.bound_by,
    )


ANGLE_TASKS: dict[int, str] = {
    1: "From the chart: is the stop below real support, and is the target before major resistance?",
    2: "From the news and the calendar: any announcement, results, or news risk inside the holding window?",
    3: "From the market and macro picture: does the regime, or any rate, inflation, or crypto-wide event, threaten this trade?",
}


async def risk_round(
    assessment: RiskAssessment,
    *,
    briefing: Briefing,
    think: Think,
    feed: Feed,
    config: DeskConfig,
    round_id: str,
) -> RiskAssessment:
    """The seats' half: analysts' notes, the Guardian's grade, the PM's size."""
    report = assessment.report(config.currency)

    async def note(seat: int, task: str, keys: str, tokens: int) -> RiskNote | None:
        prompt = (
            f"{briefing.for_seat(seat)}\n\nRISK ASSESSMENT PERIOD.\n{report}\n\n"
            f"TASK: {task}\n\n"
            f"Reply with ONLY this JSON object: {{{keys}}}"
        )
        try:
            return await ask_json(
                think, config.seat(seat), prompt, RiskNote, max_tokens=tokens, keys=keys
            )
        except StudioLLMError as error:
            await feed.emit(
                "error",
                f"{SEAT_NAMES[seat]} couldn't answer: {error}",
                seat=seat,
                round_id=round_id,
                symbol=assessment.symbol,
                stage="Risk period",
            )
            return None

    analysts = [seat for seat in (1, 2, 3) if config.seat(seat).on]
    answers = await asyncio.gather(
        *(note(seat, ANGLE_TASKS[seat], NOTE_KEYS, 260) for seat in analysts),
        note(
            4,
            "Grade this trade's risk from A (low) to F (unacceptable), and list any "
            "conditions it must meet (half size, limit order only, no overnight "
            "hold, wait until after results, and so on).",
            GUARDIAN_KEYS,
            320,
        ),
    )
    for seat, found in zip([*analysts, 4], answers, strict=True):
        if found is None:
            continue
        assessment.notes[seat] = found
        assessment.conditions.extend(found.conditions)
        text = (
            "; ".join([*found.concerns, *found.conditions])
            or found.note
            or "No concerns."
        )
        if seat == 4 and found.grade:
            assessment.guardian_grade = found.grade
            text = f"Grade {found.grade}. {text}"
        await feed.emit(
            "risk_note",
            text,
            seat=seat,
            round_id=round_id,
            symbol=assessment.symbol,
            stage="Risk period",
            data={"note": found.model_dump()},
        )
    assessment.grade = worse(assessment.code_grade, assessment.guardian_grade)
    notes = "\n".join(
        f"- {SEAT_NAMES[seat]}: "
        + (
            "; ".join([*found.concerns, *found.conditions])
            or found.note
            or "no concerns"
        )
        + (f" (grade {found.grade})" if found.grade else "")
        for seat, found in sorted(assessment.notes.items())
    )
    pm = await note(
        5,
        f"The seats' risk notes:\n{notes or '- none'}\nThe risk grade is "
        f"{assessment.grade}. Keep the size (size_factor 1), shrink it (0.1-0.99), "
        "or defer the trade. You may not make it bigger.",
        PM_KEYS,
        260,
    )
    if pm is not None:
        assessment.notes[5] = pm
        assessment.size_factor = min(1.0, max(0.0, pm.size_factor))
        assessment.deferred = pm.defer
        await feed.emit(
            "risk_note",
            (
                "Defers the trade. "
                if pm.defer
                else f"Size x{assessment.size_factor:.2f}. "
            )
            + pm.note,
            seat=5,
            round_id=round_id,
            symbol=assessment.symbol,
            stage="Risk period",
            data={"note": pm.model_dump()},
        )
    if GRADES.index(assessment.grade) > GRADES.index(config.assessment.min_grade):
        assessment.blockers.append(
            f"Risk grade {assessment.grade} is worse than the {config.assessment.min_grade} minimum."
        )
    return assessment


def resize(
    assessment: RiskAssessment, rules: Rules | None, fx: float, equity: float
) -> None:
    """Apply the Portfolio Manager's smaller size (never a bigger one)."""
    if assessment.size_factor >= 0.999:
        return
    qty = assessment.qty * assessment.size_factor
    if rules is not None:
        qty = rules.fit(qty)
    unit_risk = max(0.0, (assessment.entry - assessment.stop) * fx)
    assessment.qty = qty
    assessment.value = qty * assessment.entry * fx
    assessment.at_risk = qty * unit_risk
    assessment.at_risk_pct = assessment.at_risk / equity * 100 if equity > 0 else 0.0
    if qty <= 0:
        assessment.blockers.append(
            "Nothing is left after the Portfolio Manager's resize."
        )


def recheck(
    assessment: JsonObject,
    *,
    quote: Quote | None,
    volatility_jump_pct: float | None,
    titles_now: frozenset[str] | None,
    code: str,
    market: str,
    config: DeskConfig,
) -> list[str]:
    """After the cooling-off wait: reasons to abort, or none."""
    reasons: list[str] = []
    limits = config.assessment
    entry = assessment.get("entry")
    if quote is None:
        return ["No fresh price at the end of the wait."]
    if isinstance(entry, int | float) and entry > 0:
        moved = abs(quote.price / entry - 1) * 100
        if moved > limits.entry_band_pct:
            reasons.append(
                f"The price moved {moved:.2f}% during the wait (band {limits.entry_band_pct:g}%)."
            )
    if volatility_jump_pct is not None and volatility_jump_pct > limits.atr_spike_pct:
        reasons.append(
            f"The latest 15-minute range is {volatility_jump_pct:.0f}% above usual."
        )
    spread = quote.spread_pct
    if spread is not None and spread > SPREAD_LIMIT_PCT.get(market, 1.0):
        reasons.append(f"The bid-ask spread widened to {spread:.2f}%.")
    seen = assessment.get("titles")
    if titles_now is not None and isinstance(seen, list):
        known = {str(title) for title in seen}
        fresh = [
            title
            for title in titles_now
            if title not in known and code.casefold() in title
        ]
        if fresh:
            reasons.append(f"New headline during the wait: {fresh[0][:120]}")
    return reasons
