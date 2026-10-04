"""Ticker-format constants shared by bot/ and strategy/.

Constants only. Validation logic using them lives in the consuming packages.
"""

import re

# Uppercase symbol, 1-10 chars: letters/digits, optionally "." or "-" (e.g. BRK.B, BF-B).
TICKER_PATTERN = re.compile(r"^[A-Z][A-Z0-9]*([.\-][A-Z0-9]+)?$")
MAX_TICKER_LENGTH = 10
