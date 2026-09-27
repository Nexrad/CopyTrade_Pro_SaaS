"""
workers/worker_manager.py
----------------------------
One isolated worker per customer MT5 account (product spec section
12). Each worker owns its own executor instance and its own
connection state; a crash inside one customer's worker is caught and
logged there and never propagates to another customer's worker or to
the web process.

This uses one Python thread per customer rather than a full OS
process. On the real Windows launch machine, MetaTrader5's Python
package is most reliably driven from separate OS processes (the
underlying terminal API has per-process quirks) - if you hit that in
practice, swap ThreadPoolExecutor for multiprocessing.Process here;
WorkerManager's public interface (start_customer/execute_for_customer/
stop_customer) doesn't need to change for that swap. Threads are used
here because they're what this sandbox can actually run and verify.
"""

import logging
import threading
from typing import Optional

from security import encryption
from workers.mt5_executor import make_executor

logger = logging.getLogger("worker_manager")


class CustomerWorker:
    def __init__(self, user_id: str):
        self.user_id = user_id
        self.executor = make_executor()
        self.lock = threading.Lock()
        self.connected = False
        self.last_error: Optional[str] = None
        self._credentials: Optional[tuple] = None  # (login, password_encrypted, server), for auto-reconnect

    def connect(self, login: str, password_encrypted: str, server: str) -> bool:
        with self.lock:
            self._credentials = (login, password_encrypted, server)
            return self._connect_locked()

    def _connect_locked(self) -> bool:
        """Caller must already hold self.lock."""
        if not self._credentials:
            self.last_error = "no stored MT5 credentials"
            return False
        login, password_encrypted, server = self._credentials
        try:
            password = encryption.decrypt(password_encrypted)
            self.connected = self.executor.connect(login, password, server)
            self.last_error = None if self.connected else "login failed"
        except Exception as e:
            # A failure here must never propagate to another customer's worker.
            logger.error("worker[%s] connect failed: %s", self.user_id, e)
            self.connected = False
            self.last_error = str(e)
        finally:
            password = None  # noqa: F841  (explicitly drop plaintext reference)
        return self.connected

    def ensure_connected(self) -> bool:
        """
        Called before a risk decision is made, so 'is MT5 connected' reflects
        a live reconnect attempt rather than a stale flag left over from
        some earlier, unrelated action (spec section 12's reconnect
        requirement) - trusting a cached True/False here is exactly how a
        customer's copying could silently stay broken after one dropped
        connection until they happened to hit 'test connection' again.
        """
        with self.lock:
            if self.executor.is_connected():
                self.connected = True
                return True
            return self._connect_locked()

    def execute(self, symbol: str, direction: str, lot: float, sl=None, tp=None) -> dict:
        with self.lock:
            try:
                if not self.executor.is_connected():
                    # Product spec section 12 requires reconnect handling, not just
                    # a hard failure the first time a worker finds itself disconnected
                    # (e.g. after a process restart, or a dropped MT5 session).
                    if not self._connect_locked():
                        return {"status": "error", "ticket": None, "detail": f"MT5 reconnect failed: {self.last_error}"}
                return self.executor.place_order(symbol, direction, lot, sl, tp)
            except Exception as e:
                logger.error("worker[%s] execute failed: %s", self.user_id, e)
                self.last_error = str(e)
                return {"status": "error", "ticket": None, "detail": str(e)}

    def account_summary(self):
        with self.lock:
            try:
                return self.executor.account_summary()
            except Exception as e:
                logger.error("worker[%s] account_summary failed: %s", self.user_id, e)
                return None

    def stop(self):
        with self.lock:
            try:
                self.executor.shutdown()
            except Exception as e:
                logger.error("worker[%s] shutdown failed: %s", self.user_id, e)
            self.connected = False


class WorkerManager:
    """Process-wide registry of one CustomerWorker per customer."""

    def __init__(self):
        self._workers: dict[str, CustomerWorker] = {}
        self._registry_lock = threading.Lock()

    def get_or_create(self, user_id: str) -> CustomerWorker:
        with self._registry_lock:
            if user_id not in self._workers:
                self._workers[user_id] = CustomerWorker(user_id)
            return self._workers[user_id]

    def stop_customer(self, user_id: str):
        with self._registry_lock:
            worker = self._workers.pop(user_id, None)
        if worker:
            worker.stop()

    def status_all(self) -> dict:
        with self._registry_lock:
            return {
                uid: {"connected": w.connected, "last_error": w.last_error}
                for uid, w in self._workers.items()
            }


# One process-wide instance, imported by app/customer.py and core/signal_engine.py.
manager = WorkerManager()
