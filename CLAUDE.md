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
| `agent/` | `data`, `strategy`, `memory` (read) | `bot`, `execution` |
| `bot/` | `execution`, `memory`, `data` | `agent` |
| `execution/` | stdlib / broker SDK | `agent`, `bot` |
| `data/`, `strategy/`, `memory/` | each other as needed | `bot`, `execution` |

A shared, behavior-free contract module (e.g. the `TradeProposal` schema) will be added when proposals are implemented. Both sides may import it.

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
