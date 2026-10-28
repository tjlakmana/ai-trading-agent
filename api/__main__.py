"""python -m api [--port 8000]: serve the dashboard API on 127.0.0.1 only."""

import argparse

import uvicorn

from api.app import create_app
from api.settings import DEFAULT_PORT, ApiSettings

parser = argparse.ArgumentParser(prog="python -m api", description="Local dashboard API (loopback only).")
parser.add_argument("--port", type=int, default=DEFAULT_PORT)
args = parser.parse_args()
settings = ApiSettings(port=args.port)
print(f"Dashboard API: http://127.0.0.1:{settings.port}  (history: {settings.db_path.name}; research only, "
      "no order execution)")
uvicorn.run(create_app(settings), host=settings.host, port=settings.port, log_level="info")
