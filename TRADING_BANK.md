# Trading Bank: the autonomous build (FCC Studio 6.73.0)

What was built in stages S1 to S13 on top of the existing Trading Bank, without
a redesign. Practice (fake money on real live prices) is the default and runs
on its own; real money needs setting up on the PC and shows a standing red
warning while it is automatic; no step ever needs your approval unless you
choose "Live: I approve". Nothing here predicts profit.

Owner's rules followed throughout: never invent data, never use stale data,
fail closed, risk lives in code (not prompts), every AI answer is checked
against a strict format, and **no downgrade**: a change may only add a check
or make one stricter (where a wrong figure was fixed, the stricter of the old
and new figures is used, with "never weaker" tests).

---

## 1. Architecture summary

One process (FCC Studio) runs the desk. Its loop (every 10 seconds) and its
rounds are split into layers, each in its own module under
`src/free_claude_code/studio/trading/`:

| Layer | Modules | What it does |
| --- | --- | --- |
| Information | `data.py`, `providers/` (Yahoo, CoinGecko, DexScreener, Coinbase and Kraken books, ASX and Yahoo news, Hyperliquid), `information.py`, `news.py`, `quality.py` | Every price carries its source, its own time, real-time or delayed; news is dated, judged (confirmed, priced in, material); data-quality checks block new buys when a critical one fails |
| Evidence | `evidence.py`, `briefing.py` | A numbered evidence pack (F facts, C calculations, N news, M market, P portfolio, R research, O opinions, W web) with sources, times, a cut-off and a hash; web text fenced as data |
| Debate | `debate.py`, `contract.py`, `breaks.py`, `simulate.py`, `compare.py`, `infotest.py`, `seats.py` | Four rounds (blind openings, compare, cross-exam, updated views, pre-mortem, closings, PM decision); research, brainstorm and simulation between rounds; strict answer format; information stress test; Guardian review with veto; final challenge |
| Decision | `engine.py`, `scorecard.py`, `conflicts.py`, `regime.py`, `assessment.py`, `stress.py`, `risk.py`, `precheck.py` | Plain-code rules (each with measured value and limit), scorecard, regime policy, investment stress test, hard limits, the account check |
| Records | `decisions.py`, `log.py`, `records.py` | One decision record per cycle (timings, prices, evidence, seats, rules, result) and an audit trail that is never pruned |
| Protection | `protection.py`, `desk.py` | Circuit breaker, latching kill switch, alert-only mode, live-key health checks |
| Execution | `brokers/`, `fills.py`, `positions.py`, `resilience.py` | Send-once orders, fill deltas, unconfirmed orders kept open, realistic practice fills, the position manager |
| Reliability | `worker.py` | One desk at a time (lease), heartbeat, step timing, job retries and dead letters, metrics |
| Learning and testing | `learning.py`, `forecasts.py`, `backtest.py` | Versioned vote weights with a held-back test; a backtest of the rules on closed daily candles |
| Keys | `keyvault.py`, `brokers/common.py` | Encrypted keys (Windows DPAPI), redaction, the no-money-moves guard |
| Invo | `brokers/hyperliquid.py`, `hlsign.py`, `providers/hyperliquid.py` | Hyperliquid account through an API wallet, signing checked against the official SDK |

The PC page (`api/studio_static/trade.js`) shows all of it in the existing
tabs; the routes are in `api/studio_routes.py`.

## 2. Workflow diagram

```
 every 10 s (only the FCC holding the lease)
 ┌──────────────────────────────────────────────────────────────────────┐
 │ re-check unmatched orders → sync orders/fills → watch positions      │
 │ (stops, targets, +1R, trailing, time exit; runs even when stopped,   │
 │ breaker or kill) → circuit breaker → cooling-off orders → approvals  │
 │ → score forecasts → learning (6 h) → live key check (10 min, live)   │
 └──────────────────────────────────────────────────────────────────────┘
 a round (one candidate at a time)
   scan ─► data-quality checks ──fail──► stop (holdings still reviewed)
             │ pass
             ▼
          evidence pack [F1][C2][N3]…
             ▼
   round 1: blind openings → compare in code → cross-exam
   break: research questions · brainstorm · simulate 2,000 paths
   round 2: updated views → rebuttals      (break)
   round 3: updated views → pre-mortem → Guardian replies   (break)
   round 4: closings → PM decision (checked format)
             ▼
   information stress test ─fail─► no trade (reason recorded)
   Guardian review (veto) → decision engine → scorecard → regime policy
   → investment stress test (can only shrink or stop)
             ▼
   stale? (price left the band) ──► discard, analyse again
             ▼
   risk round (A–F) → hard limits → cooling-off → account check
             ▼
   alert-only? → alert │ practice → paper fills │ live → platform
             ▼
   fills (deltas) → position → manager → exit → P&L → debrief → learning
 every step writes the decision record and the audit trail
```

## 3. Files changed

Commits on `claude/multi-agent-local-models-app-s6uxxh` (82 files, about
22,000 lines with tests):

| Stage | Commit | Main files |
| --- | --- | --- |
| S1 data checks | d594bda, cbe73f5 | `information.py`, `news.py`, `quality.py`, `providers/orderbook.py`, `providers/news.py`, `data.py`, `precheck.py`, `desk.py` |
| S2 evidence pack | 5cbfe81, cca5661 | `evidence.py`, `contract.py`, `jsonish.py`, `records.py` (TradeEvidence) |
| S3 debate | eecf67e, 4e560f7 | `debate.py`, `contract.py`, `breaks.py`, `simulate.py`, `compare.py`, `infotest.py`, `research.py` |
| S4 decision layer | e133f4e | `engine.py`, `scorecard.py`, `conflicts.py`, `regime.py`, `stress.py`, `assessment.py` |
| S5 records | e8e0b96 | `decisions.py`, `log.py`, `store.py` (decisions, audit) |
| S6 protection | ed4f9f2 | `protection.py`, `config.py`, `desk.py`, `trade.js` |
| S7 execution | 81aaf7b, d61ef8a | `fills.py`, `positions.py`, `brokers/paper.py`, `brokers/coinspot.py`, `brokers/swyftx.py`, `brokers/webhook.py`, `resilience.py`, `records.py` (TradeFill) |
| S8 reliability | 4dd0487 | `worker.py` |
| S9 learning | 3ef2afa | `learning.py`, `records.py` (TradeWeights) |
| S10 backtest | 28c116c | `backtest.py` |
| S11 keys | 3e3bc8c | `keyvault.py`, `brokers/common.py`, `brokers/registry.py`, `service.py` |
| S13 Invo | 98b8d70 | `hlsign.py`, `brokers/hyperliquid.py`, `providers/hyperliquid.py`, `vendor/hyperliquid-python-sdk/` |
| S12 dashboard and release | this commit | `trade.js`, `trade.css`, `README.md`, `guide.py`, `TRADING_BANK.md`, version 6.73.0 |

Tests added: `test_trading_quality.py`, `test_trading_evidence.py`,
`test_trading_contract.py`, `test_trading_rounds.py`,
`test_trading_engine.py`, `test_trading_fills.py`,
`test_trading_positions.py`, `test_trading_worker.py`,
`test_trading_learning.py`, `test_trading_backtest.py`,
`test_trading_keyvault.py`, `test_trading_hyperliquid.py`, plus many in
`test_trading_desk.py`, `test_trading_brokers.py` and
`e2e/test_trading_page.py`.

## 4. What is real and what is mocked

Real (in the app):
- Market data from Yahoo, CoinGecko, DexScreener, Coinbase and Kraken public
  books, ASX announcements, Yahoo Finance news, Hyperliquid's public API.
- Every check, rule, stress test, simulation, record, breaker, kill switch,
  practice fill, position manager step, learning step and backtest.
- Platform adapters talk to the real APIs with your keys. Beta adapters
  (CoinSpot, Swyftx, Hyperliquid) were built from the platforms' published
  APIs and checked against their documentation or SDK test values, not yet
  against a live account.
- Hyperliquid signing is verified against the official SDK's exact test
  signatures (vendored).

Mocked (in tests only): the seats' model answers, the market data servers,
the platforms (a fake broker, a mock Hyperliquid exchange, recorded
responses), and Windows' key protection (a test lock stands in on Linux).

## 5. Setup (on the PC)

1. Update FCC to 6.73.0 (unzip every part of the release into one folder).
2. Trade → Setup: practice mode is on by default. Choose markets, seats'
   models, debate rounds (4), and limits.
3. Optional: Setup → Paper account → *Practice coin prices* → Hyperliquid's
   live book, to practise on Invo's market.
4. For real money later: Setup → Platforms → your platform → paste keys
   (trade-only keys; never withdrawal) → Save → Test → *Yes, this is my
   account*. Then Mode → Live (the typed phrase for automatic).
5. Invo: on app.hyperliquid.xyz connect the wallet your Invo account uses,
   More → API → create an API wallet; paste its private key and your account
   address into *Hyperliquid / Invo*. Try *testnet* first.

## 6. Worker deployment

Nothing extra to run: the desk's loop starts with FCC Studio on the PC and
carries on after a restart (practice resumes by itself; real money waits for
Start). Only one FCC runs the desk at a time (a lease file in
`%USERPROFILE%\.fcc\…\trading\desk.lease`, renewed every pass; a second copy
waits). Desk → Engine shows the loop, the last pass, each step's errors,
retries and dead letters, and fill and slippage figures; the same is at
`GET /studio/api/trading/health`.

## 7. Risk and threat review

| Threat | What stops it |
| --- | --- |
| Stale, delayed, future-dated or wrong-coin prices | Price times checked per market; real bid/ask required live; sources must agree; failing critical checks block buys |
| A web page or headline steering the seats | Web text fenced as data; seats must cite numbered evidence; facts only from dated sources |
| A model talking past a limit | Limits, stress tests, engine rules and sizing are plain code; answers in a strict format or ignored |
| Acting on an old decision after a long debate | Stale-decision rule: discarded and analysed again |
| Duplicate orders | Client ids; lookups before any resend; unconfirmable orders stay open (never resent); one desk at a time |
| Partial fills double counted | Fills recorded as deltas (TradeFill) |
| Losses compounding | Daily loss stop, losing-streak and slippage breakers, regime policy, stress limits (3% a trade, 12% the portfolio) |
| Positions left without stops | Watching runs while stopped, breaker or kill; platform stops kept on a kill; close-everything retries at the open |
| Key theft or leakage | Keys encrypted (DPAPI), never shown, redacted from feed/audit/logs; account numbers never derived from keys |
| Money moved out | Withdraw/transfer calls refused before they leave the PC; keys with transfer rights refused; Hyperliquid API wallet can't withdraw; FCC signs only orders, cancels, leverage |
| Keys revoked or account swapped | Live key check every 10 min switches real money off |
| Learning drifting into risk | Vote weights only, small checked steps, rollback; never limits or safety |
| Futures leverage (Invo) | 1x isolated, long only, exchange-held stop with every buy |

## 8. Test results

At release: `./scripts/ci.sh --skip playwright` (format, lint, types,
suppression ban) all pass; **7,360 tests passed, 280 skipped** (Content Farm
and the cartoon tests left out by your rule); browser tests
`e2e/test_trading_page.py` 3 passed. The end-to-end tests cover: an
information run ending in "no trade" with its saved record, and a practice
run through a partial fill, a restart (no duplicate order), the rest of the
fill, a stop exit, P&L, the decision record and the audit trail.

## 9. Failure recovery

| Failure | What happens |
| --- | --- |
| FCC closed mid-order | On start every "submitting" order is matched with its platform first; one that can't be matched stays open, pauses new trades, and is asked about every 5 minutes |
| Lost answer from a platform | Looked up by client id; if nobody can say, it stays open (never resent) and the breaker pauses new trades; you can reset after checking the account (it is then marked unconfirmed) |
| Internet down | The desk waits and says so; carries on when it is back |
| A step keeps failing | Timed and recorded; errors over the limit trip the breaker |
| A debrief fails | Tried again after 2 and 4 minutes, then set aside and recorded |
| Bad data streak | Breaker trips after 5 candidates in a row fail the checks |
| Keys fail | Real money switches off; positions still watched |
| Second FCC opened | It waits; the first keeps the desk |

## 10. Known limitations

- Beta adapters (CoinSpot, Swyftx, Hyperliquid) haven't been tried on a live
  account: start with testnet/demo or a small order. CoinSpot and Swyftx
  have no client ids, so an unsure order needs you to check the account.
- Secure key storage uses Windows DPAPI; on other systems FCC stays in
  practice.
- The backtest replays the rules, not the seats' debate, and uses today's
  symbol list (delisted symbols are missing).
- Practice fills are a model of the market (spread, slippage, depth), not a
  record of real fills; ASX prices from Yahoo are about 20 minutes late.
- Hyperliquid funding is shown and is in the exchange's account value, but
  practice positions don't accrue funding, and the stress test doesn't add it.
- MAE/MFE come from the prices FCC checks every few seconds; moves between
  checks can be missed.
- The phone app wasn't changed (you asked for PC only for now).

## 11. Config reference (Setup, or `trading/desk.json`)

| Setting | Default | Meaning |
| --- | --- | --- |
| `mode` | `paper` | `paper` (practice), `alert_only`, `live_approve`, `live_auto` |
| `debate_rounds` | 4 | 1–6 rounds with research between |
| `practice_book` | `exchanges` | Practice coin prices: `exchanges` or `hyperliquid` |
| `routes` | none | Real money: each market's own account |
| `risk.risk_per_trade_pct` | 1.0 | Most of the account a trade may lose at its stop |
| `risk.max_position_pct` / `max_order_value` | 10 / 1,000 | Largest holding and order |
| `risk.max_open_positions` / `max_trades_per_day` | 5 / 6 | |
| `risk.max_daily_loss_pct` | 3.0 | Daily loss stop (also trips the breaker) |
| `risk.min_confidence` / `min_consensus` | 0.6 / 0.55 | |
| `assessment.stress_trade_pct` / `stress_account_pct` | 3 / 12 | Worst stressed loss per trade and for the portfolio |
| `assessment.min_stop_atr` | 1.0 | Stop at least this many ATRs away |
| `assessment.max_decision_minutes` | 60 | Older decisions are stale |
| `breaker.*` | 3 losses, slippage ×2, 5 errors/30 min, 5 bad-data rounds, 60 min cool-down | Circuit breaker |
| `data.*` | per market | Price age limits, spread limits, minimum turnover, price conflict tolerance |

Learning (fixed in code, not settings): 50 samples per seat, 30% held back,
10% a step, ×0.5–×2.

## 12. How to stop it immediately

- **Kill switch** (top of the Trade page, PC or phone): stops the desk,
  cancels every waiting order on every account, and stays on until you
  release it on the PC. Type *CLOSE EVERYTHING* to also sell every holding.
- **Stop** stops new trades but keeps watching stops and targets.
- **Mode → Practice** switches real money off at once (works from the phone).
- **Remove keys** on a platform (PC) takes that account away completely; on
  Hyperliquid you can also revoke the API wallet on app.hyperliquid.xyz.
