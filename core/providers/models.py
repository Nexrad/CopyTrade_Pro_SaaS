"""
core/providers/models.py
---------------------------
The normalized signal object that flows: Telegram -> parser -> signal
engine -> per-customer risk check -> order. Nothing here talks to
Telegram or MT5.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class ParsedSignal:
    provider: str
    raw_text: str
    direction: str            # "BUY" or "SELL"
    symbol: str
    entry_min: Optional[float] = None
    entry_max: Optional[float] = None
    sl: Optional[float] = None
    tp: Optional[float] = None
    sender: Optional[str] = None
