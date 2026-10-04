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
| `agent/` | **Thinks** | Gathers context, prompts Claude, returns a structured proposal (ticker, action, confidence, entry, stop loss, take profit, reasoning). Never executes. |
| `bot/` | **Controls** | Validates proposals, enforces stop-loss, exposure, and daily-loss rules, sizes positions, approves or rejects, and forwards approved orders to execution. Deterministic Python only. |
| `execution/` | **Executes** | Broker interface with a paper-trading implementation. Called only by the bot. |
| `data/` | Inputs | Market data, TradingView (via MCP), indicators, news, sentiment. |
| `strategy/` | Ideas | Named strategies and analysis templates, so performance can be tracked per strategy. |
| `memory/` | Audit trail | External, auditable store of every proposal, decision, and outcome. The bot writes, the agent reads. Claude does not "learn"; past trades are retrieved explicitly. |
| `tests/` | Safety net | Unit tests plus architecture tests that enforce the boundaries above. |

### Example proposal (future)

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
- [ ] Trade proposal schema (shared contract between agent and bot)
- [ ] Deterministic risk manager and position sizing
- [ ] Paper execution (simulated, then paper broker API)
- [ ] Trade memory (SQLite)
- [ ] Claude agent integration
- [ ] Market data, indicators, TradingView via MCP
- [ ] News and sentiment
- [ ] Backtesting, analytics, dashboard

Each component is built and tested independently before it is wired in.
