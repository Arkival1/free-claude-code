"""The decision engine: every rule a buy must pass before the order is made,
each with what was measured and the limit, all checked in plain code.

The rules here are added on top of everything that already checked the
buy (the data checks, the debate's checks, the risk report, the seats' risk
round) and the hard limits that run again when the order is placed. A
failing blocking rule stops the buy; nothing here can make one bigger or
let one through that something else stopped.
"""

from dataclasses import dataclass

from free_claude_code.core.json_types import JsonObject

from .regime import RegimePolicy


@dataclass(frozen=True, slots=True)
class RuleCheck:
    rule: str
    passed: bool
    measured: float | str | None
    limit: float | str | None
    unit: str = ""
    detail: str = ""
    blocking: bool = True

    def line(self) -> str:
        shown = (
            f"{self.measured:g}" if isinstance(self.measured, float) else self.measured
        )
        limit = f"{self.limit:g}" if isinstance(self.limit, float) else self.limit
        unit = f" {self.unit}" if self.unit else ""
        verdict = "ok" if self.passed else ("BLOCKS" if self.blocking else "warning")
        return (
            f"{self.rule}: {verdict} (measured {shown if shown is not None else 'unknown'}"
            f"{unit}, limit {limit if limit is not None else 'none'}{unit})"
            + (f" - {self.detail}" if self.detail else "")
        )

    def view(self) -> JsonObject:
        return {
            "rule": self.rule,
            "passed": self.passed,
            "measured": self.measured,
            "limit": self.limit,
            "unit": self.unit,
            "detail": self.detail,
            "blocking": self.blocking,
        }


@dataclass(frozen=True, slots=True)
class BuyFacts:
    """What the engine measures a proposed buy by."""

    data_ok: bool
    data_summary: str
    stop_atr: float | None
    min_stop_atr: float
    reward_risk: float | None
    min_reward_risk: float
    confidence: float
    min_confidence: float
    consensus: float
    min_consensus: float
    trades_today: int | None
    max_trades_per_day: int
    objections_left: int
    answered: int
    stress_blocked: bool | None
    stress_reasons: tuple[str, ...]
    stress_worst_pct: float | None
    stress_limit_pct: float
    info_blocked: bool | None
    conflicts_blocking: bool
    conflict_reasons: tuple[str, ...]


def buy_rules(facts: BuyFacts, policy: RegimePolicy) -> list[RuleCheck]:
    """Every rule, evaluated whether or not an earlier one failed."""
    found: list[RuleCheck] = []
    found.append(
        RuleCheck(
            "Data good enough to trade",
            facts.data_ok,
            "ok" if facts.data_ok else "blocking checks",
            "no blocking data check",
            detail="" if facts.data_ok else facts.data_summary,
        )
    )
    found.append(
        RuleCheck(
            "The market's mood allows new trades",
            policy.allow_new_trades,
            policy.kind + (" (extreme)" if policy.extreme else ""),
            "not extreme",
            detail=policy.note,
        )
    )
    min_stop = facts.min_stop_atr * policy.stop_atr_factor
    found.append(
        RuleCheck(
            "Stop far enough from the entry",
            facts.stop_atr is not None and facts.stop_atr >= min_stop - 1e-9,
            round(facts.stop_atr, 3) if facts.stop_atr is not None else None,
            round(min_stop, 3),
            unit="ATR",
            detail=""
            if facts.stop_atr is not None
            else "the ATR isn't known, so the stop's distance can't be checked",
        )
    )
    found.append(
        RuleCheck(
            "Reward for the risk",
            facts.reward_risk is not None
            and facts.reward_risk >= facts.min_reward_risk - 1e-9,
            round(facts.reward_risk, 3) if facts.reward_risk is not None else None,
            facts.min_reward_risk,
            unit="to 1",
        )
    )
    min_confidence = min(0.99, facts.min_confidence + policy.confidence_add)
    found.append(
        RuleCheck(
            "Confidence (the lower of the manager's and the scorecard's)",
            facts.confidence >= min_confidence - 1e-9,
            round(facts.confidence, 3),
            round(min_confidence, 3),
        )
    )
    found.append(
        RuleCheck(
            "The seats' weighted chance of a rise",
            facts.consensus >= facts.min_consensus - 1e-9,
            round(facts.consensus, 3),
            facts.min_consensus,
        )
    )
    allowed = int(facts.max_trades_per_day * policy.trades_factor)
    found.append(
        RuleCheck(
            "Trades today (with the market's mood)",
            facts.trades_today is not None and facts.trades_today < allowed,
            facts.trades_today,
            allowed,
            detail=""
            if facts.trades_today is not None
            else "today's trades couldn't be counted",
        )
    )
    found.append(
        RuleCheck(
            "Every standing blocking objection answered",
            facts.answered >= facts.objections_left,
            facts.answered,
            facts.objections_left,
        )
    )
    if facts.stress_blocked is None:
        found.append(
            RuleCheck(
                "Investment stress test",
                False,
                "not run",
                "within limits",
                detail="the stress test couldn't run, so the buy can't be checked",
            )
        )
    else:
        found.append(
            RuleCheck(
                "Investment stress test",
                not facts.stress_blocked,
                round(facts.stress_worst_pct, 3)
                if facts.stress_worst_pct is not None
                else None,
                facts.stress_limit_pct,
                unit="% of the account",
                detail="; ".join(facts.stress_reasons),
            )
        )
    found.append(
        RuleCheck(
            "Information stress test",
            facts.info_blocked is False,
            "passed"
            if facts.info_blocked is False
            else "not run"
            if facts.info_blocked is None
            else "stopped",
            "passed",
        )
    )
    found.append(
        RuleCheck(
            "No conflict that blocks the trade",
            not facts.conflicts_blocking,
            "blocking conflict" if facts.conflicts_blocking else "none",
            "none",
            detail="; ".join(facts.conflict_reasons),
        )
    )
    return found


def blockers(checks: list[RuleCheck]) -> list[str]:
    return [check.line() for check in checks if check.blocking and not check.passed]
