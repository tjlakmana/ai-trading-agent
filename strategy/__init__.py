"""Deterministic trading strategy ("strategy decides the setup").

Version 1 pipeline (experimental, Ross Cameron-inspired small-cap momentum):
    1. In-play filter          (in_play.py)  - implemented
    2. Momentum impulse        - not yet
    3. Micro-pullback          - not yet
    4. Entry trigger -> TradeProposal         - not yet

Boundary rules:
- Deterministic Python only. AI output may enter only as recorded input data
  (e.g. a Catalyst with its source); it never decides a threshold.
- Must never import `bot`, `execution`, `agent`, or `anthropic`
  (enforced by tests/test_architecture.py).
- Produces proposals at most; never approves or executes.
"""
