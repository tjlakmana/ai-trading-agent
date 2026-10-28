"""Persistent, auditable memory (external, explicit; Claude does not "learn").

Implemented:
    scan_store.py      append-only SQLite scanner history (runtime/memory.db):
                       every scan attempt, every row, every check, replayable
    classification.py  QUALIFIED / NEAR_MISS / FILTERED_OUT view of in-play results
    serialize.py       explicit JSON serialization (no pickle)
    Manual inspection: python -m memory runs | show | ticker | replay

Eventually: trade memory recording every proposal, the bot's approve/reject
decision and reason, market context, entry/exit, and P&L, kept separate from
scanner history (TRADE_DB_PATH). The bot writes trade records; the agent may
read relevant history. Memory is data retrieved per request.

Must never import bot/, execution/, agent/ or an LLM SDK (enforced by
tests/test_architecture.py).
"""
