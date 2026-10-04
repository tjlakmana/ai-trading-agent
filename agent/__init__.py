"""AI Trading Agent: the reasoning layer ("the agent thinks").

Eventually: gathers context (market data, indicators, news, sentiment,
portfolio state, relevant past trades from memory), asks Claude to analyze
it, and returns a structured trade proposal.

Boundary rules:
- Produces proposals only. Never executes trades.
- Must never import from `bot` or `execution` (enforced by tests/test_architecture.py).
- Has no access to risk limits, position sizing, or trading mode.
"""
