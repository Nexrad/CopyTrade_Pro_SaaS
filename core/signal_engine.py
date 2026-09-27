"""
core/signal_engine.py
------------------------
Parse ONCE, then fan out to every eligible customer CONCURRENTLY
(product spec sections 4 and 6) - never parse the same Telegram
message per-customer, and never process customers sequentially.

Flow:
    raw Telegram text
      -> provider.parse()              (once)
      -> duplicate_guard fingerprint   (once)
      -> load eligible customers       (one query)
      -> ThreadPoolExecutor: risk check + order execution PER CUSTOMER,
         concurrently, each wrapped so one customer's exception/MT5
         failure can never affect another customer's trade or crash
         the fan-out itself (spec section 6/12's hard isolation
         requirement).
"""

import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from core import risk
from core.duplicate_guard import is_duplicate, make_fingerprint
from core.providers.registry import ACTIVE_PROVIDERS
from workers.worker_manager import manager as worker_manager

logger = logging.getLogger("signal_engine")


def _get_runtime_flag(conn, key: str, default: bool = False) -> bool:
    row = conn.execute("SELECT value FROM runtime_settings WHERE key = ?", (key,)).fetchone()
    if row is None:
        return default
    return row["value"] == "1"


def _eligible_customers(conn):
    """One query - not one query per customer."""
    return conn.execute("""
        SELECT
            u.id AS user_id, u.is_active,
            cs.copy_enabled, cs.provider_enabled, cs.fixed_lot,
            cs.max_open_trades, cs.max_daily_loss, cs.max_drawdown_percent,
            a.status AS access_status,
            m.id AS mt5_account_id, m.login, m.password_encrypted, m.server
        FROM users u
        JOIN customer_settings cs ON cs.user_id = u.id
        LEFT JOIN access a ON a.user_id = u.id AND a.status = 'active'
        LEFT JOIN mt5_accounts m ON m.user_id = u.id
        WHERE u.role = 'customer'
    """).fetchall()


def _open_trades_count(conn, user_id: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM orders WHERE user_id = ? AND status = 'filled'", (user_id,)
    ).fetchone()
    return row["c"] if row else 0


def _daily_loss_so_far(conn, user_id: str) -> float:
    # MVP: no closed-trade P/L tracking yet (order fills are recorded, closes are not) -
    # returns 0.0, i.e. "no loss counted yet". Documented in README as a real gap, not hidden.
    return 0.0


def _execute_for_customer(conn_factory, row, signal_id: str, symbol: str, direction: str, sl, tp) -> dict:
    """Runs in its own thread. Any exception here is caught - never bubbles up
    to the fan-out loop or another customer's future."""
    conn = conn_factory()
    user_id = row["user_id"]
    try:
        emergency = _get_runtime_flag(conn, "global_emergency_stop", default=False)
        worker = worker_manager.get_or_create(user_id)
        mt5_connected = worker.ensure_connected()

        decision = risk.evaluate(
            user_is_active=bool(row["is_active"]),
            access_status=row["access_status"] or "expired",
            copy_enabled=bool(row["copy_enabled"]),
            provider_enabled=bool(row["provider_enabled"]),
            mt5_connected=mt5_connected,
            global_emergency_stop=emergency,
            open_trades_count=_open_trades_count(conn, user_id),
            max_open_trades=row["max_open_trades"],
            daily_loss_so_far=_daily_loss_so_far(conn, user_id),
            max_daily_loss=row["max_daily_loss"],
            drawdown_percent_so_far=0.0,
            max_drawdown_percent=row["max_drawdown_percent"],
            lot_size=row["fixed_lot"],
            symbol=symbol,
        )

        order_id = uuid.uuid4().hex
        now = time.strftime("%Y-%m-%dT%H:%M:%S")

        if not decision.allowed:
            conn.execute(
                "INSERT INTO orders (id, user_id, signal_id, symbol, direction, lot, status, error_detail, requested_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 'rejected', ?, ?)",
                (order_id, user_id, signal_id, symbol, direction, row["fixed_lot"], decision.reason, now),
            )
            conn.commit()
            return {"user_id": user_id, "status": "rejected", "reason": decision.reason}

        result = worker.execute(symbol, direction, row["fixed_lot"], sl, tp)
        status = result["status"]
        conn.execute(
            "INSERT INTO orders (id, user_id, signal_id, symbol, direction, lot, status, broker_ticket, error_detail, requested_at, executed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (order_id, user_id, signal_id, symbol, direction, row["fixed_lot"],
             status, result.get("ticket"), result.get("detail"), now, now),
        )
        conn.commit()
        return {"user_id": user_id, "status": status, "reason": result.get("detail")}

    except Exception as e:
        # Hard isolation guarantee: this customer's failure is logged and
        # returned as a result - it never raises out of this function.
        logger.error("signal fan-out failed for user %s: %s", user_id, e)
        return {"user_id": user_id, "status": "error", "reason": str(e)}


def handle_incoming_message(conn_factory, text: str, sender: Optional[str] = None, max_workers: int = 20) -> dict:
    """
    Entry point called exactly once per incoming Telegram message,
    regardless of how many customers are subscribed.
    """
    conn = conn_factory()

    parsed = None
    for provider in ACTIVE_PROVIDERS.values():
        parsed = provider.parse(text, sender=sender)
        if parsed:
            break

    if parsed is None:
        return {"parsed": False, "reason": "not an entry signal"}

    fingerprint = make_fingerprint(parsed.provider, parsed.symbol, parsed.direction, parsed.entry_min, parsed.entry_max)
    if is_duplicate(conn, fingerprint):
        return {"parsed": True, "duplicate": True, "signal": parsed.__dict__}

    signal_id = uuid.uuid4().hex
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    conn.execute(
        "INSERT INTO signals (id, provider, raw_text, direction, symbol, entry_min, entry_max, sl, tp, fingerprint, received_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (signal_id, parsed.provider, parsed.raw_text, parsed.direction, parsed.symbol,
         parsed.entry_min, parsed.entry_max, parsed.sl, parsed.tp, fingerprint, now),
    )
    conn.commit()

    customers = _eligible_customers(conn)

    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [
            pool.submit(_execute_for_customer, conn_factory, row, signal_id, parsed.symbol, parsed.direction, parsed.sl, parsed.tp)
            for row in customers
        ]
        for future in as_completed(futures):
            results.append(future.result())

    return {"parsed": True, "duplicate": False, "signal_id": signal_id, "signal": parsed.__dict__, "results": results}
