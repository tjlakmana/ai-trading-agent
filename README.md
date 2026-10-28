# Hybrid AI Trading System

An educational and research project combining a deterministic trading strategy, an AI assistant (Claude) for contextual interpretation, and a deterministic, rule-enforcing trading bot.

> **PAPER TRADING ONLY.** This project does not and will not execute live-money trades in its current phase. It is not financial advice.

## Design Principle

> **AI INTERPRETS. STRATEGY DECIDES THE SETUP. BOT CONTROLS THE RISK. EXECUTION EXECUTES.**

- **AI (Claude) interprets** context: it reads news, classifies catalysts, and explains why something may matter. It never decides whether a numerical threshold passed, never sets a position size, and never executes.
- **The strategy decides the setup.** Deterministic Python detects in-play stocks and entry conditions, and eventually creates the `TradeProposal`.
- **The bot controls the risk.** Deterministic validation and risk rules approve or reject every proposal. No LLM is involved.
- **Execution executes** only what the bot approved (paper trading only).

## Architecture

```
 Market Data ──────────────►  Deterministic In-Play Filter        (strategy/)  ✔ V1
 News ──► AI interprets ──┐                │
   (catalyst, context)    └──────►  Deterministic Momentum Impulse Detector    ☐
                                           │
                                    Deterministic Micro-Pullback Detector      ☐
                                           │
                                    Deterministic Entry Trigger                ☐
                                           │
                                     TradeProposal
 ══════════════════════ trust boundary ════╪═════════════════════
                                           ▼
                                  TRADING BOT (deterministic)      (bot/)
                                    ├─ Structural validation                   ✔
                                    └─ Risk manager + position sizing          ✔
                                           │
                     APPROVE ──────────────┼──── REJECT / NO_ACTION → recorded
                        │
                        ▼
              Paper Trading Execution      (execution/)                        ☐
                        │
                        ▼
          Trade Result → Trade Memory      (memory/)                           ☐
```

AI output is an *input* (for example, a classified `Catalyst` with its source recorded). Deterministic code always makes the decisions. Nothing upstream of the bot can call the broker, change risk limits, disable the risk manager, override a rejection, change sizing rules, or switch to live trading.

## Components

| Package | Role | Eventually does |
|---|---|---|
| `core/` | Contracts | Data-only types and constants: `TradeProposal`, `Position`, `AccountState`, `ScannerSnapshot`, `Catalyst`, ticker format. No logic. |
| `strategy/` | **Decides the setup** | Deterministic in-play filter, then momentum impulse, micro-pullback, and entry trigger. It eventually creates the `TradeProposal`. Never executes. |
| `agent/` | **Interprets** | Claude reads news, classifies catalysts, and summarizes context. It supplies inputs to the strategy and decides nothing. |
| `bot/` | **Controls the risk** | Validates proposals, enforces stop-loss, exposure and daily-loss rules, sizes positions, and approves or rejects. Deterministic Python only. |
| `execution/` | **Executes** | Broker interface with a paper-trading implementation. Called only by the bot. |
| `data/` | Inputs | Finviz Elite discovery (implemented), later a real-time intraday feed, TradingView (via MCP), indicators, news. Produces `ScannerSnapshot`s. |
| `memory/` | Audit trail | External, auditable store of every scan, proposal, decision and outcome. Claude does not "learn"; past trades are retrieved explicitly. |
| `tests/` | Safety net | Unit tests plus architecture tests that enforce the boundaries above. |

## Strategy: in-play filter (V1)

An **experimental, Ross Cameron-inspired small-cap momentum** hypothesis. It does **not** claim to reproduce Ross Cameron's exact rules. Every threshold is a Version 1 development hypothesis that we expect to change after backtesting and paper trading.

`strategy.in_play.evaluate_in_play(snapshot, config)` turns a raw `ScannerSnapshot` into an `InPlayResult`. That result contains:
- `qualified`
- `reasons` and `warnings`
- one entry per check, with the actual value and the threshold
- the calculated metrics
- the **unchanged raw snapshot** and the config used

`evaluate_universe` does the same for a list of stocks and keeps every result, failures included.

Each criterion has a **level**: HARD (must pass; missing data fails), PREFERRED (a warning only), or OFF. Moving a criterion between levels is a config change in `strategy/in_play_config.py`, never a code change.

| Criterion | V1 level | V1 experimental default |
|---|---|---|
| Price | HARD | $2.00 – $20.00 |
| % change from previous close | HARD | ≥ +10% |
| Volume vs average daily volume | HARD / PREFERRED | ≥ 3× / ≥ 5× |
| Float | HARD / PREFERRED | ≤ 20M / ≤ 10M shares |
| Catalyst present | PREFERRED | (no news source yet) |
| Room to daily resistance | PREFERRED | ≥ 20% (placeholder hypothesis) |
| Minimum cumulative volume | HARD when set | off by default; separate regular-session and premarket thresholds |
| Gap %, premarket volume | Raw research | recorded only |

The minimum cumulative volume check uses `min_premarket_cumulative_volume` when `open_price` is `None` (before the regular-session open) and `min_cumulative_volume` otherwise. Both are `None` (disabled) by default.

**`volume_vs_avg_daily` is not conventional relative volume (RVOL).** It divides *partial* session volume by an average *full-day* volume, so it can substantially understate unusual volume early in the session. A separate, time-of-day-adjusted `relative_volume_tod` will be added once intraday volume history exists.

**"Qualified" only means a stock moves on to the momentum-impulse stage.** It is not a trade signal.

## Data: Finviz Elite discovery (V1)

Finviz Elite's Screener API (`data/finviz/`) is used **for stock discovery only**. Its server-side filters narrow the market to a candidate list. Our in-play filter then re-evaluates every candidate from raw data.

```
FinvizScreenConfig ─► FinvizClient ─► parse_screener_csv ─► ScannerSnapshot ─► evaluate_universe ─► FinvizScan
 (verified codes)      (HTTP, limits)   (units, missing data)                    (strategy/, deterministic)
```

- **Discovery screen (V1 starting hypothesis, not Warrior Trading's rules):** `sh_price_2to20`, `sh_relvol_o2`, `sh_curvol_o500`, `sh_float_u20`, `ta_change_u`.
- **Only verified filter codes are accepted.** Finviz silently ignores unknown codes, so a typo would quietly widen the screen. New codes must be verified against a live response first (`data/finviz/schema.py`).
- **Raw fields become `ScannerSnapshot` fields:**
  - Price, Prev Close and Open are in dollars.
  - Volume is in whole shares.
  - Average Volume is in thousands, so it is multiplied by 1,000.
  - Shares Float is in millions, so it is multiplied by 1,000,000.
- **Finviz-calculated values are vendor data, never inputs to our checks.** These are Relative Volume, Change, Change from Open, Gap and Performance (1 min to 1 h). They are kept in `FinvizRecord.vendor`.
- **Freshness:** Finviz provides no quote timestamp. `fetched_at` is recorded, `quote_time` is `None` and `quote_freshness` is `UNKNOWN`. `ScannerSnapshot.as_of` is set to `fetched_at`.
- **Bad data:** a row missing Ticker, Price, Prev Close or Volume gets no snapshot. It is kept in `FinvizScan.rejected` with its reasons. An unexpected CSV header rejects the whole response.
- **Limits:**
  - Requests are paced client-side at 10 per rolling 5 seconds, which is Finviz Elite's limit.
  - HTTP 429 is retried after `Retry-After`, a bounded number of times.
  - Requests time out after 10 s.
- **Secrets:** the key is read from `FINVIZ_API_KEY`. The process environment is checked first, then `.env`. Finviz requires the key in the query string, so it is kept out of exceptions, `repr` and logs, and `urllib3`'s debug log is redacted.

Manual scan (research only; it places no orders):

```bash
python -m data.finviz                 # default discovery screen + in-play filter (min volume 500,000)
python -m data.finviz --show-all      # also list stocks that did not qualify, with reasons
python -m data.finviz --tickers AAPL,TSLA --min-volume 0
```

**What Finviz cannot provide:**
- **No quote timestamps.**
- **No premarket volume.**
- **No 1-minute bars or ticks, and no streaming.**
- **No halts, and no daily resistance levels.**
- **Column behavior outside the regular session is unverified.** Every row fetched outside the regular session carries a warning.

Polling gives snapshots, not events. Breakout and high-of-day triggers need a real-time intraday feed.

## Bot: validation and risk (V1)

Version 1 is **long-only**:

- **BUY** opens a long position. A stop loss is required; take profit is optional.
- **SELL** closes an existing long position. It never opens a short, and there is no partial-sell quantity yet.
- **HOLD** means no trade.
- Proposals never contain quantities; the bot decides size.

The bot works in two stages: **structural validation** (is the proposal well-formed?) and then **risk approval** (is it allowed?). Passing validation does not mean a trade is approved.

`bot.risk.evaluate(proposal, account, config)` returns a `RiskDecision`: **APPROVE**, **REJECT** or **NO_ACTION** (for HOLD). It includes the quantity, the reasons and a full sizing breakdown. Only APPROVE can ever reach execution.

- **BUY:** the bot sizes the position as the smallest of three limits:
  - the risk budget, divided by the stop distance. The budget is 1% of the lower of current and start-of-day equity, further capped by the remaining daily-loss allowance.
  - the room left under the per-ticker exposure cap (20% of equity)
  - the available cash
- **Daily loss:** once equity falls 3% below start-of-day equity, new BUYs stop. Gains earlier in the day never enlarge this allowance or the per-trade risk.
- **SELL:** closes the entire existing long position. It is allowed even after the daily limit is reached. With no position, it is rejected.
- **HOLD:** returns NO_ACTION and is never executed.

The 1% / 20% / 3% limits are **development and testing defaults only, not recommendations for real-money trading.** They are set in `bot/risk_config.py`, which neither the agent nor the strategy can import.

## Getting Started

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env    # fill in locally; never commit .env
python main.py          # prints foundation status
pytest                  # runs tests (fully mocked: no network, never reads your .env)
python -m data.finviz   # manual Finviz in-play scan (needs FINVIZ_API_KEY in .env)
```

## Status / Roadmap

- [x] Project foundation and architecture boundaries
- [x] Trade proposal schema (`core/proposal.py`) and structural validation (`bot/validation.py`)
- [x] Deterministic risk manager and position sizing (`bot/risk.py`)
- [x] Strategy layer 1: deterministic in-play filter (`strategy/in_play.py`)
- [ ] Strategy layer 2: momentum impulse detector
- [ ] Strategy layer 3: micro-pullback detector
- [ ] Strategy layer 4: entry trigger and `TradeProposal` creation
- [ ] Paper execution (simulated, then paper broker API)
- [ ] Trade memory (SQLite)
- [x] Finviz Elite discovery provider (`data/finviz/`) feeding the in-play filter
- [ ] Real-time intraday market data feed (required for high-of-day / breakout triggers)
- [ ] Indicators, TradingView via MCP
- [ ] News integration and AI catalyst interpretation
- [ ] Time-of-day relative volume (`relative_volume_tod`)
- [ ] Backtesting, analytics, dashboard

Each component is built and tested independently before it is wired in.
