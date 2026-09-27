"""
workers/mt5_executor.py
--------------------------
One interface, two implementations, so the rest of the app (risk
engine, signal engine, worker manager) never knows or cares which one
is running underneath.

RealMT5Executor: imports the MetaTrader5 package, which only installs
and runs on Windows with a real terminal. This is UNTESTED in this
sandbox - I have no Windows machine or MT5 terminal here. It's kept
intentionally thin (connect/login/place_order/account_summary) so
that testing it on your actual machine is a small, isolated task
rather than something tangled through the rest of the codebase.

DryRunExecutor: simulates connect/login/order placement in memory.
Used automatically whenever DRY_RUN=true (the default) or when the
MetaTrader5 package isn't importable (e.g. this sandbox, or any
non-Windows dev machine) - this is what every test in tests/ actually
runs against, and what makes the rest of this system genuinely
verifiable before you ever risk real money or even have MT5 installed.
"""

import time
import uuid
from abc import ABC, abstractmethod
from typing import Optional

from config import settings


class MT5ExecutorInterface(ABC):
    @abstractmethod
    def connect(self, login: str, password: str, server: str) -> bool: ...

    @abstractmethod
    def is_connected(self) -> bool: ...

    @abstractmethod
    def place_order(self, symbol: str, direction: str, lot: float, sl: Optional[float], tp: Optional[float]) -> dict:
        """Returns {"status": "filled"|"rejected"|"error", "ticket": str|None, "detail": str|None}"""
        ...

    @abstractmethod
    def account_summary(self) -> Optional[dict]: ...

    @abstractmethod
    def shutdown(self) -> None: ...


class DryRunExecutor(MT5ExecutorInterface):
    """In-memory simulation - real logic path, fake broker."""

    def __init__(self):
        self._connected = False
        self._balance = 10_000.0

    def connect(self, login: str, password: str, server: str) -> bool:
        # Simulates a real login round-trip without a real broker.
        time.sleep(0)  # placeholder for realistic async use later
        self._connected = bool(login and password and server)
        return self._connected

    def is_connected(self) -> bool:
        return self._connected

    def place_order(self, symbol: str, direction: str, lot: float, sl=None, tp=None) -> dict:
        if not self._connected:
            return {"status": "error", "ticket": None, "detail": "not connected"}
        return {"status": "filled", "ticket": uuid.uuid4().hex[:10], "detail": None}

    def account_summary(self) -> Optional[dict]:
        if not self._connected:
            return None
        return {"balance": self._balance, "equity": self._balance, "margin": 0.0, "free_margin": self._balance}

    def shutdown(self) -> None:
        self._connected = False


class RealMT5Executor(MT5ExecutorInterface):
    """
    Windows + real MetaTrader5 package only. NOT exercised by any test
    in this project - verify this class specifically on your Legion PC
    with a real (ideally demo) MT5 account before trusting it with
    real money.
    """

    def __init__(self):
        import MetaTrader5 as mt5  # deferred import: only required if this class is actually used
        self._mt5 = mt5
        self._connected = False

    def connect(self, login: str, password: str, server: str) -> bool:
        if not self._mt5.initialize(path=settings.MT5_TERMINAL_PATH):
            self._connected = False
            return False
        ok = self._mt5.login(int(login), password=password, server=server)
        self._connected = bool(ok)
        return self._connected

    def is_connected(self) -> bool:
        try:
            info = self._mt5.terminal_info()
            self._connected = info is not None
        except Exception:
            self._connected = False
        return self._connected

    def place_order(self, symbol: str, direction: str, lot: float, sl=None, tp=None) -> dict:
        order_type = self._mt5.ORDER_TYPE_BUY if direction == "BUY" else self._mt5.ORDER_TYPE_SELL
        request = {
            "action": self._mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": lot,
            "type": order_type,
            "sl": sl or 0.0,
            "tp": tp or 0.0,
            "type_filling": self._mt5.ORDER_FILLING_IOC,
        }
        try:
            result = self._mt5.order_send(request)
            if result is None or result.retcode != self._mt5.TRADE_RETCODE_DONE:
                detail = getattr(result, "comment", "order_send returned no result")
                return {"status": "rejected", "ticket": None, "detail": detail}
            return {"status": "filled", "ticket": str(result.order), "detail": None}
        except Exception as e:
            return {"status": "error", "ticket": None, "detail": str(e)}

    def account_summary(self) -> Optional[dict]:
        info = self._mt5.account_info()
        if info is None:
            return None
        return {
            "balance": info.balance, "equity": info.equity,
            "margin": info.margin, "free_margin": info.margin_free,
        }

    def shutdown(self) -> None:
        self._mt5.shutdown()
        self._connected = False


def make_executor() -> MT5ExecutorInterface:
    """
    DRY_RUN (default true) always gets the simulator - this is the
    safety switch: even on the real Windows machine with MT5
    installed, DRY_RUN=true in .env means no real order is ever sent.
    """
    if settings.DRY_RUN:
        return DryRunExecutor()
    try:
        return RealMT5Executor()
    except ImportError:
        # MetaTrader5 package not installed on this machine (e.g. any
        # non-Windows environment) - fail safe to the simulator rather
        # than crash, but this should never happen on the real launch
        # machine with DRY_RUN=false.
        return DryRunExecutor()
