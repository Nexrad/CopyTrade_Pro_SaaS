"""
core/duplicate_guard.py
--------------------------
Time-windowed idempotency, not permanent blacklisting (product spec
section 14 - explicit example: GOLD SELL 4500 -> SL hit -> price
returns to 4500 -> provider re-posts the same setup -> that new
signal MUST be allowed).

Fingerprint = provider + symbol + direction + entry (rounded) +
time bucket. Two messages that hash to the same fingerprint within
the same DUPLICATE_WINDOW_SECONDS bucket are treated as one signal
(protects against Telegram delivering/parsing the same message
twice); once the bucket rolls over, an identical setup is a brand
new signal.
"""

import time

from config import settings


def make_fingerprint(provider: str, symbol: str, direction: str, entry_min, entry_max) -> str:
    bucket = int(time.time() // settings.DUPLICATE_WINDOW_SECONDS)
    entry_key = round(entry_min, 1) if entry_min is not None else "MKT"
    return f"{provider}:{symbol}:{direction}:{entry_key}:{bucket}"


def is_duplicate(conn, fingerprint: str) -> bool:
    row = conn.execute("SELECT 1 FROM signals WHERE fingerprint = ?", (fingerprint,)).fetchone()
    return row is not None
