"""
core/providers/marshallfx.py
-------------------------------
Ab Marshall's signal format (reused/adapted from the old bot's
providers/marshallfx/parser.py + strategy.py - real, previously-tested
logic, not rewritten from scratch):

    GOLD sell now
    SL 4554
    TP 4400

Key rules (unchanged from the proven old parser):
  - Direction + symbol live on the FIRST line; SL/TP live further down.
  - Most signals are market orders with no entry price - only some
    give one, on the first line.
  - A message only counts as an entry signal if it has BOTH a
    direction word AND an SL value - this filters out chatter like
    "TP1 smashed" or "move SL to 4043", which are real channel
    messages but not new entries.
  - Only TP1 is used (multi-TP scale-outs aren't automated).
  - Default lot 0.01, 5-pip entry tolerance - same defaults as before.
"""

import re
from typing import Optional

from core.providers.base import BaseProvider
from core.providers.models import ParsedSignal

_SYMBOL_KEYWORDS = {
    "XAUUSD": "XAUUSDm", "XAU": "XAUUSDm", "GOLD": "XAUUSDm",
    "BTCUSD": "BTCUSDm", "BTC": "BTCUSDm", "BITCOIN": "BTCUSDm",
}


def _detect_symbol(text: str, default: str = "XAUUSDm") -> str:
    up = text.upper()
    for kw, sym in _SYMBOL_KEYWORDS.items():
        if kw in up:
            return sym
    return default


def _extract_direction(text: str) -> Optional[str]:
    low = text.lower()
    if "buy" in low:
        return "BUY"
    if "sell" in low:
        return "SELL"
    return None


def _extract_entry_range(text: str):
    numbers = re.findall(r"\d+\.\d+|\d+", text)
    if len(numbers) >= 2:
        a, b = float(numbers[0]), float(numbers[1])
        return min(a, b), max(a, b)
    if len(numbers) == 1:
        v = float(numbers[0])
        return v, v
    return None


def _extract_tp_sl(text: str) -> dict:
    up = text.upper()
    sl_match = re.search(r"SL\D{0,5}(\d+\.?\d*)", up)
    tp_match = re.search(r"TP\D{0,5}(\d+\.?\d*)", up)
    return {
        "sl": float(sl_match.group(1)) if sl_match else None,
        "tp": float(tp_match.group(1)) if tp_match else None,
    }


class AbMarshallProvider(BaseProvider):
    name = "AbMarshall"
    telegram_channel = "marshallfx_free_channel"
    lot_size_default = 0.01
    pip_tolerance = 5

    def parse(self, text: str, sender: Optional[str] = None) -> Optional[ParsedSignal]:
        first_line = text.split("\n", 1)[0]

        direction = _extract_direction(first_line)
        if direction is None:
            return None  # status update / chit-chat, not an entry

        tp_sl = _extract_tp_sl(text)
        if tp_sl["sl"] is None:
            return None  # Ab Marshall always states SL on real entry signals

        symbol = _detect_symbol(text)
        entry_range = _extract_entry_range(first_line)

        return ParsedSignal(
            provider=self.name,
            raw_text=text,
            direction=direction,
            symbol=symbol,
            entry_min=entry_range[0] if entry_range else None,
            entry_max=entry_range[1] if entry_range else None,
            sl=tp_sl["sl"],
            tp=tp_sl["tp"],
            sender=sender,
        )
