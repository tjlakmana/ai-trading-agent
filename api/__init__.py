"""Local dashboard API (FastAPI): a viewer over scanner data, never a controller.

    python -m api            serves http://127.0.0.1:8000 (loopback only)

Reads recorded scanner history (memory/) and can trigger one guarded manual
Finviz scan at a time. It cannot place orders, change risk rules, or reach
bot/, execution/, agent/ or an LLM SDK (enforced by tests/test_architecture.py).
Responses never contain credentials or authenticated URLs.

Data honesty:
- Finviz data carries fetched_at (when we received it). Finviz provides no
  quote timestamp, so quote_time is always null and freshness is UNKNOWN.
- Values are grouped by origin: `market` (raw Finviz inputs, units
  converted), `calculated` (our deterministic metrics) and `vendor`
  (Finviz-calculated, for discovery only).
- Modules without a real data source are reported as unavailable by
  GET /api/modules. They are never filled with placeholder data.
"""
