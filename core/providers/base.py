"""
core/providers/base.py
--------------------------
Common shape every provider follows, so the signal engine never needs
to know which specific provider it's talking to. Only Ab Marshall is
implemented for this launch (product spec section 5), but a second
provider is added by dropping in one more module here and registering
it in core/providers/registry.py - the engine itself doesn't change.
"""

from abc import ABC, abstractmethod
from typing import Optional

from core.providers.models import ParsedSignal


class BaseProvider(ABC):
    name: str
    telegram_channel: str

    @abstractmethod
    def parse(self, text: str, sender: Optional[str] = None) -> Optional[ParsedSignal]:
        """Return a ParsedSignal if text is a real entry signal, else None."""
        raise NotImplementedError
