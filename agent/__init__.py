"""AI agent: the interpretation layer ("AI interprets").

Eventually: Claude reads news, classifies catalysts (into core.market.Catalyst,
with its source recorded), summarizes why news may matter, and writes
contextual explanations.

Boundary rules:
- Interprets only. Never decides whether a numerical strategy threshold passed,
  never sets position size, never creates approvals, never executes.
- Must never import from `bot` or `execution` (enforced by tests/test_architecture.py).
- Has no access to risk limits, position sizing, or trading mode.
"""
