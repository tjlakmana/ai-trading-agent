# Hybrid AI Trading System

An educational and research project combining an AI reasoning agent (Claude) with a deterministic, rule-enforcing trading bot.

> **PAPER TRADING ONLY.** This project does not and will not execute live-money trades in its current phase. It is not financial advice.

## Design Principle

> **The agent thinks. The bot controls and executes.**

Claude analyzes information and *proposes* trades. Deterministic Python code decides whether a proposal is allowed and whether it is executed. No LLM sits in the path that enforces risk controls.

## Architecture

```
 Market Data / TradingView ─┐
 News & Sentiment ──────────┤
 Portfolio State ───────────┼──►  AI TRADING AGENT (Claude)
 Trade Memory (read) ───────┘              │
                                           ▼
                                Structured Trade Proposal
                                           │
 ══════════════════════ trust boundary ════╪═════════════════════
                                           ▼
                                  TRADING BOT (deterministic)
                                    ├─ Proposal validation
                                    ├─ Risk manager
                                    └─ Position sizing
                                           │
                               Approved? ──┴── Rejected → recorded
                                   │
                                   ▼
                          Paper Trading Execution
                                   │
                                   ▼
                     Trade Result → Trade Memory (write)
                                   │
                                   └──► available to the agent for future analysis
```

A proposal is only data. The agent cannot call the broker, change risk limits, disable the risk manager, override a rejection, change sizing rules, or switch to live trading. Those capabilities exist only on the bot side of the boundary.

## Components

| Package | Role | Eventually does |
|---|---|---|
| `core/` | Contract | Data-only types shared by agent and bot (`TradeProposal`, `Action`, `Position`, `AccountState`). No logic. |
| `agent/` | **Thinks** | Gathers context, prompts Claude, returns a structured proposal (ticker, action, confidence, entry, stop loss, take profit, reasoning). Never executes. |
| `bot/` | **Controls** | Validates proposals, enforces stop-loss, exposure, and daily-loss rules, sizes positions, approves or rejects, and forwards approved orders to execution. Deterministic Python only. |
| `execution/` | **Executes** | Broker interface with a paper-trading implementation. Called only by the bot. |
| `data/` | Inputs | Market data, TradingView (via MCP), indicators, news, sentiment. |
| `strategy/` | Ideas | Named strategies and analysis templates, so performance can be tracked per strategy. |
| `memory/` | Audit trail | External, auditable store of every proposal, decision, and outcome. The bot writes, the agent reads. Claude does not "learn"; past trades are retrieved explicitly. |
| `tests/` | Safety net | Unit tests plus architecture tests that enforce the boundaries above. |

Version 1 is **long-only**:

- **BUY** opens a long position. A stop loss is required; take profit is optional.
- **SELL** closes an existing long position. It never opens a short, and there is no partial-sell quantity yet.
- **HOLD** means no trade.
- Proposals never contain quantities; the bot decides size.

The bot works in two stages: **structural validation** (is the proposal well-formed?) and then **risk approval** (is it allowed?). Passing validation does not mean a trade is approved.

### Risk manager (V1)

`bot.risk.evaluate(proposal, account, config)` returns a `RiskDecision`: **APPROVE**, **REJECT** or **NO_ACTION** (for HOLD). It includes the quantity, the reasons and a full sizing breakdown. Only APPROVE can ever reach execution.

- **BUY:** the bot sizes the position as the smallest of three limits:
  - the risk budget, divided by the stop distance. The budget is 1% of the lower of current and start-of-day equity, further capped by the remaining daily-loss allowance.
  - the room left under the per-ticker exposure cap (20% of equity)
  - the available cash
- **Daily loss:** once equity falls 3% below start-of-day equity, new BUYs stop. Gains earlier in the day never enlarge this allowance or the per-trade risk.
- **SELL:** closes the entire existing long position. It is allowed even after the daily limit is reached. With no position, it is rejected.
- **HOLD:** returns NO_ACTION and is never executed.

The 1% / 20% / 3% limits are **development and testing defaults only, not recommendations for real-money trading.** They are set in `bot/risk_config.py`, which the agent cannot access.

### Example proposal

```
Ticker: NVDA      Action: BUY       Confidence: 0.84
Entry: 185.00     Stop Loss: 179.00 Take Profit: 197.00
Reasoning: Positive sentiment, bullish trend, and increasing volume.
```

The bot may still reject this. For example, it could exceed exposure limits, the stop could be too wide, or the daily loss limit could already be reached.

## Getting Started

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env    # fill in locally; never commit .env
python main.py          # prints foundation status
pytest                  # runs tests
```

## Status / Roadmap

- [x] Project foundation and architecture boundaries
- [x] Trade proposal schema (`core/proposal.py`) and structural validation (`bot/validation.py`)
- [x] Deterministic risk manager and position sizing (`bot/risk.py`)
- [ ] Paper execution (simulated, then paper broker API)
- [ ] Trade memory (SQLite)
- [ ] Claude agent integration
- [ ] Market data, indicators, TradingView via MCP
- [ ] News and sentiment
- [ ] Backtesting, analytics, dashboard

Each component is built and tested independently before it is wired in.
