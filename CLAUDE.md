# CLAUDE.md: Project Development Rules

Hybrid AI trading system for education and research. Read README.md for the architecture.

**Core principle: THE AGENT THINKS. THE BOT CONTROLS AND EXECUTES.**

## Non-negotiable safety rules

1. **Paper trading only.** Never implement, stub, or scaffold live-money trading. Never add a config flag, env var, or CLI option that could enable live trading. If a task seems to require it, stop and ask.
2. **The agent never executes.** Code in `agent/` must never import `bot` or `execution`, and must never call broker APIs. It only returns proposals (data). `tests/test_architecture.py` enforces this. Never weaken or skip that test.
3. **No LLM in the control path.** Validation, risk rules, position sizing, exposure limits, daily loss limits, and approve/reject decisions are deterministic Python in `bot/`. Never route them through Claude or any model.
4. **The agent cannot change the rules.** Risk limits and sizing rules are owned by `bot/`. They are never read from agent output, and the agent cannot modify them at runtime. Rejections are final; there is no override path.
5. **Only `bot/` calls `execution/`.** Execution happens only after an explicit approval.
6. **No secrets in code.** API keys, tokens, and passwords come from environment variables (`.env`, which is gitignored). Never hardcode them, log them, or put real values in `.env.example`.
7. **Treat agent output as untrusted input.** The bot must validate every field (types, ranges, stop/target placement relative to entry, known ticker) and reject anything malformed.

## Package boundaries

| Package | May import | Must not import |
|---|---|---|
| `core/` | stdlib only | any other project package |
| `agent/` | `core`, `data`, `strategy`, `memory` (read) | `bot`, `execution` |
| `bot/` | `core`, `execution`, `memory`, `data` | `agent`, `anthropic` (no LLM SDKs) |
| `execution/` | `core`, stdlib / broker SDK | `agent`, `bot` |
| `data/`, `strategy/`, `memory/` | `core`, each other as needed | `bot`, `execution` |

`core/` holds data-only contracts (e.g. `TradeProposal`): no validation, no logic, no I/O. All validation lives in `bot/`.

## Trading semantics (Version 1: long-only)

- **BUY**: open or add to a long position. Requires entry and a stop loss below entry. Take profit is optional by design, because some future strategies may use other exit mechanisms. If set, it must be above entry.
- **SELL**: close an EXISTING long position. It never opens a short. Stop loss and take profit must not be set. `entry` is the proposed exit price (None means exit at market). Portfolio ownership checks come later, once portfolio state exists.
- **HOLD**: no trade. No price fields may be set.
- **No quantities in proposals.** The agent never specifies size. Position sizing, and any future partial-sell quantity, is decided by the bot. Do not add a quantity field to `TradeProposal` in V1.
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
