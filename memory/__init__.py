"""Persistent, auditable trade memory.

Eventually: an external store (e.g. SQLite) recording every proposal,
the bot's approve/reject decision and reason, market context, entry/exit,
and P&L. The bot writes records; the agent may read relevant past trades.
Claude does not "learn" — memory is explicit data retrieved per request.
"""
