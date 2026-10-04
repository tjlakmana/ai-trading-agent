"""Paper-trading execution layer.

Eventually: a broker interface with a paper-trading implementation that
fills orders approved by the bot and reports fills and positions.

Boundary rules:
- PAPER TRADING ONLY. No live-money implementation exists in this project.
- Called only by `bot`. The agent must never import this package.
"""
