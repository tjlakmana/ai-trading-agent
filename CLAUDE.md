# CLAUDE.md: Project Development Rules

Hybrid AI trading system for education and research. Read README.md for the architecture.

**Core principle: AI INTERPRETS. STRATEGY DECIDES THE SETUP. BOT CONTROLS THE RISK. EXECUTION EXECUTES.**

## Non-negotiable safety rules

1. **Paper trading only.** Never implement, stub, or scaffold live-money trading. Never add a config flag, env var, or CLI option that could enable live trading. If a task seems to require it, stop and ask.
2. **The agent never executes or decides.** Code in `agent/` must never import `bot` or `execution`, and must never call broker APIs. The AI interprets context only: it reads news, classifies catalysts and writes explanations. It never decides whether a numerical threshold passed. `tests/test_architecture.py` enforces the import rules. Never weaken or skip those tests.
3. **The strategy decides setups deterministically.** Code in `strategy/` is deterministic Python. It must never import `bot`, `execution`, `agent` or `anthropic`. The strategy eventually creates `TradeProposal`s. AI output enters only as recorded input data, such as a `Catalyst` with its `source`.
4. **No LLM in the control path.** Validation, risk rules, position sizing, exposure limits, daily loss limits, and approve/reject decisions are deterministic Python in `bot/`. Never route them through Claude or any model.
5. **Nothing upstream can change the rules.** Risk limits and sizing rules are owned by `bot/`. They are never read from agent or strategy output, and neither can modify them at runtime. Rejections are final; there is no override path.
6. **Only `bot/` calls `execution/`.** Execution happens only after an explicit approval.
7. **No secrets in code.** API keys, tokens, and passwords come from environment variables (`.env`, which is gitignored). Never hardcode them, log them, or put real values in `.env.example`.
8. **Treat every proposal as untrusted input.** The bot must validate every field (types, ranges, stop/target placement relative to entry, known ticker) and reject anything malformed.

## Package boundaries

| Package | May import | Must not import |
|---|---|---|
| `core/` | stdlib only | any other project package |
| `agent/` | `core`, `data`, `strategy`, `memory` (read) | `bot`, `execution` |
| `strategy/` | `core`, `data`, `memory` | `bot`, `execution`, `agent`, `anthropic` |
| `bot/` | `core`, `execution`, `memory`, `data` | `agent`, `anthropic` (no LLM SDKs) |
| `execution/` | `core`, stdlib / broker SDK | `agent`, `bot` |
| `data/`, `memory/` | `core`, each other, `strategy` as needed | `bot`, `execution` |

`core/` holds data-only contracts and constants (`TradeProposal`, `AccountState`, `ScannerSnapshot`, ticker format in `core/symbols.py`). It has no validation, no logic and no I/O. Validation lives in the consuming package (`bot/`, `strategy/`).

## Trading semantics (Version 1: long-only)

- **BUY**: open or add to a long position. Requires entry and a stop loss below entry. Take profit is optional by design, because some future strategies may use other exit mechanisms. If set, it must be above entry.
- **SELL**: close an EXISTING long position. It never opens a short. Stop loss and take profit must not be set. `entry` is the proposed exit price (None means exit at market). Portfolio ownership checks come later, once portfolio state exists.
- **HOLD**: no trade. No price fields may be set.
- **No quantities in proposals.** Proposals never specify size. Position sizing, and any future partial-sell quantity, is decided by the bot. Do not add a quantity field to `TradeProposal` in V1.
- Short selling is out of scope. Do not implement it.

## Validity is not approval

`ValidationResult.is_valid` means only that a proposal is structurally well-formed. It must never be treated as approval to execute. Approval is a separate decision made by the deterministic risk manager. Never send an order to `execution/` based on `is_valid` alone.

## Risk manager (`bot/risk.py`)

- **`evaluate(proposal, account, config)` is the only entry point.** It runs structural validation itself, so invalid proposals can never be evaluated as if they were valid.
- **It returns a `RiskDecision`:** `APPROVE`, `REJECT` or `NO_ACTION` (for HOLD). **Only `Decision.APPROVE` may ever reach execution.**
- **The bot alone decides quantity.** Proposals carry no size, and agent confidence must not affect sizing or approval.
- **Account state (`core/portfolio.py`) comes from the bot's source of truth,** never from the agent. Bad account data is rejected (fail closed).
- **BUY sizing:** `quantity = min(qty_by_risk, qty_by_exposure, qty_by_cash)`, in whole shares, rounded down with a relative tolerance of 1e-9. The formulas are in the module docstring.
- **Daily loss:**
  - `daily_loss = max(0, start_of_day_equity - equity)`, which includes open losses.
  - When the daily limit is reached, every BUY is rejected.
  - The remaining daily allowance also caps each BUY's risk budget.
  - **Profits never enlarge the daily allowance.**
- **Per-trade risk** is `min(equity, start_of_day_equity) × max_risk_per_trade_pct`. Intraday profits never increase it, and intraday losses reduce it.
- **SELL** approves closing the entire existing long position. It is never blocked by the daily-loss limit, because exiting reduces exposure. With no position, it is rejected, so short selling is impossible.
- **`RiskConfig` (`bot/risk_config.py`)** is defined in code and owned by the bot. Never read it from agent output, a proposal or environment variables.
- **Development defaults (1% risk per trade, 20% max position, 3% max daily loss) are for development and testing only.** They are not recommendations for real-money trading. Do not present them as such.

## Strategy: in-play filter (`strategy/in_play.py`)

- **This is an experimental, Ross Cameron-inspired hypothesis.** Never describe its parameters as Ross Cameron's exact rules. Every default in `strategy/in_play_config.py` is a V1 development hypothesis that will be tuned after backtesting and paper trading.
- **Every criterion has a level:** HARD (must pass; missing data fails closed), PREFERRED (warning only) or OFF. Change categories and thresholds through `InPlayConfig`. Never hard-code a threshold in evaluation logic.
- **Always preserve the raw data.** Every result keeps the unchanged `ScannerSnapshot`, the calculated metrics and the config. Every check runs even after a HARD failure. `evaluate_universe` keeps the stocks that fail.
- **Calculate derived metrics in our own code** (% change, gap, volume ratio, room to resistance). Never trust a vendor's or an AI's pre-calculated value.
- **`volume_vs_avg_daily` is NOT relative volume (RVOL).** It divides partial session volume by average full-day volume, so it understates unusual volume early in the session. Never rename it or describe it as RVOL. Time-of-day RVOL will be a separate `relative_volume_tod` metric.
- **V1 levels:** catalyst and room to resistance are PREFERRED (there's no news source yet; the 20% room is a placeholder). Price $2–$20 is HARD.
- **`qualified` means only "proceed to the next strategy stage".** It is never a trade signal or approval.

## Development workflow

- Build one component at a time and test it in isolation before wiring it in.
- Explain substantial design decisions and get agreement before implementing them.
- Do not add frameworks or dependencies until they are actually needed. Keep `requirements.txt` minimal and accurate.
- Every risk rule needs unit tests, including rejection and edge cases.
- Memory is external and auditable. Record approvals *and* rejections with reasons. Never assume Claude retains anything between calls.
- Run `pytest` before reporting work as done.

## Conventions

- Python 3.11+, type hints, standard library first.
- Keep modules small and single-purpose. Prefer plain functions and dataclasses over class hierarchies.
- Runtime files (databases, logs) go in `runtime/` / `logs/`, which are gitignored.
