"""Deterministic Trading Bot: the control layer ("the bot controls and executes").

Eventually: validates incoming trade proposals, enforces risk rules
(stop-loss validation, position sizing, exposure limits, daily loss limits),
approves or rejects each proposal, forwards approved orders to the
paper-execution layer, and records outcomes.

Boundary rules:
- Pure, deterministic Python. No LLM calls in any risk or approval path.
- Risk limits are defined here in code/config the agent cannot modify.
- The only path to `execution`.
"""
