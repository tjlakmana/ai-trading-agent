"""Entry point for the hybrid AI trading system (paper trading only).

Components are not wired together yet. This only confirms the project
foundation loads and reports its status.
"""

import sys

COMPONENTS = ("core", "agent", "bot", "data", "strategy", "execution", "memory")


def main() -> int:
    print("Hybrid AI Trading System - PAPER TRADING ONLY")
    print("The agent thinks. The bot controls and executes.")
    for name in COMPONENTS:
        __import__(name)
        print(f"  [ok] {name} (not implemented yet)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
