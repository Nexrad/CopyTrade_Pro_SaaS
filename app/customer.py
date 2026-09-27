"""
app/customer.py
------------------
Everything a logged-in customer can do (product spec section 7).
Every function takes user_id explicitly and every query filters by
it - this is the actual customer-isolation enforcement point
(see tests/test_customer_isolation.py).
"""

import base64
import os
import time
import uuid

from config import settings
from security import encryption
from workers.worker_manager import manager as worker_manager


class CustomerError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


# ---------- Profile / access status ----------

def get_status(conn, user_id: str) -> dict:
    # created_at has 1-second resolution, so two access rows created in the
    # same second (e.g. registration's default row + an approval moments
    # later) can tie - `rowid` is SQLite's implicit insertion-order column
    # and breaks that tie deterministically in favor of the newest row.
    access = conn.execute(
        "SELECT * FROM access WHERE user_id = ? ORDER BY created_at DESC, rowid DESC LIMIT 1", (user_id,)
    ).fetchone()
    settings_row = conn.execute("SELECT * FROM customer_settings WHERE user_id = ?", (user_id,)).fetchone()
    mt5 = conn.execute("SELECT id, login, server, connected, last_error FROM mt5_accounts WHERE user_id = ?", (user_id,)).fetchone()
    return {
        "access": dict(access) if access else None,
        "settings": dict(settings_row) if settings_row else None,
        "mt5_account": dict(mt5) if mt5 else None,
    }


# ---------- MT5 account ----------

def add_or_update_mt5_account(conn, user_id: str, login: str, password: str, server: str) -> dict:
    if not login or not password or not server:
        raise CustomerError("login, password, and server are all required")

    existing = conn.execute("SELECT id FROM mt5_accounts WHERE user_id = ?", (user_id,)).fetchone()
    encrypted = encryption.encrypt(password)
    now = time.strftime("%Y-%m-%dT%H:%M:%S")

    if existing:
        conn.execute(
            "UPDATE mt5_accounts SET login=?, password_encrypted=?, server=?, connected=0, last_error=NULL, last_checked_at=? WHERE id=?",
            (login, encrypted, server, now, existing["id"]),
        )
        account_id = existing["id"]
    else:
        account_id = uuid.uuid4().hex
        conn.execute(
            "INSERT INTO mt5_accounts (id, user_id, login, password_encrypted, server, connected, created_at) "
            "VALUES (?, ?, ?, ?, ?, 0, ?)",
            (account_id, user_id, login, encrypted, server, now),
        )
    conn.commit()
    return {"id": account_id, "login": login, "server": server}
    # NOTE: password is never returned here or anywhere else, per spec section 7 ("never
    # display the password again after saving") and section 16.


def test_mt5_connection(conn, user_id: str) -> dict:
    row = conn.execute("SELECT * FROM mt5_accounts WHERE user_id = ?", (user_id,)).fetchone()
    if not row:
        raise CustomerError("No MT5 account on file")

    worker = worker_manager.get_or_create(user_id)
    connected = worker.connect(row["login"], row["password_encrypted"], row["server"])
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    conn.execute(
        "UPDATE mt5_accounts SET connected=?, last_error=?, last_checked_at=? WHERE id=?",
        (1 if connected else 0, worker.last_error, now, row["id"]),
    )
    conn.commit()
    return {"connected": connected, "error": worker.last_error}


# ---------- Risk / copy settings ----------

_UNSET = object()  # sentinel so "explicitly set to null" differs from "field omitted"


def update_risk_settings(conn, user_id: str, *, fixed_lot=None, max_open_trades=None,
                          max_daily_loss=_UNSET, max_drawdown_percent=_UNSET) -> dict:
    row = conn.execute("SELECT * FROM customer_settings WHERE user_id = ?", (user_id,)).fetchone()
    if not row:
        raise CustomerError("Settings not found")

    fixed_lot = row["fixed_lot"] if fixed_lot is None else float(fixed_lot)
    max_open_trades = row["max_open_trades"] if max_open_trades is None else int(max_open_trades)
    max_daily_loss = row["max_daily_loss"] if max_daily_loss is _UNSET else max_daily_loss
    max_drawdown_percent = row["max_drawdown_percent"] if max_drawdown_percent is _UNSET else max_drawdown_percent

    if fixed_lot <= 0:
        raise CustomerError("fixed_lot must be positive")
    if max_open_trades <= 0:
        raise CustomerError("max_open_trades must be positive")

    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    conn.execute(
        "UPDATE customer_settings SET fixed_lot=?, max_open_trades=?, max_daily_loss=?, max_drawdown_percent=?, updated_at=? WHERE user_id=?",
        (fixed_lot, max_open_trades, max_daily_loss, max_drawdown_percent, now, user_id),
    )
    conn.commit()
    return get_status(conn, user_id)["settings"]


def set_copy_enabled(conn, user_id: str, enabled: bool):
    conn.execute("UPDATE customer_settings SET copy_enabled=? WHERE user_id=?", (1 if enabled else 0, user_id))
    conn.commit()


def set_provider_enabled(conn, user_id: str, enabled: bool):
    conn.execute("UPDATE customer_settings SET provider_enabled=? WHERE user_id=?", (1 if enabled else 0, user_id))
    conn.commit()


# ---------- Payments ----------

def submit_payment(conn, user_id: str, method: str, claimed_amount, receipt_filename: str, receipt_b64: str) -> dict:
    if method not in ("telebirr", "cbe"):
        raise CustomerError("Unsupported payment method")
    if not receipt_b64:
        raise CustomerError("Receipt file is required")

    user_dir = os.path.join(settings.RECEIPTS_DIR, user_id)
    os.makedirs(user_dir, exist_ok=True)
    safe_name = f"{uuid.uuid4().hex}_{os.path.basename(receipt_filename or 'receipt')}"
    receipt_path = os.path.join(user_dir, safe_name)
    with open(receipt_path, "wb") as f:
        f.write(base64.b64decode(receipt_b64))

    payment_id = uuid.uuid4().hex
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    conn.execute(
        "INSERT INTO payments (id, user_id, method, claimed_amount, receipt_path, status, submitted_at) "
        "VALUES (?, ?, ?, ?, ?, 'pending_review', ?)",
        (payment_id, user_id, method, claimed_amount, receipt_path, now),
    )
    conn.commit()
    return {"id": payment_id, "status": "pending_review"}


def list_my_payments(conn, user_id: str) -> list:
    rows = conn.execute(
        "SELECT id, method, claimed_amount, status, rejection_reason, submitted_at, reviewed_at FROM payments "
        "WHERE user_id = ? ORDER BY submitted_at DESC", (user_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def get_receipt_path_for_owner(conn, user_id: str, payment_id: str) -> str:
    """Enforces spec section 16: receipts only accessible to their owner (or an admin, via admin.py)."""
    row = conn.execute("SELECT receipt_path FROM payments WHERE id = ? AND user_id = ?", (payment_id, user_id)).fetchone()
    if not row:
        raise CustomerError("Receipt not found", status=404)
    return row["receipt_path"]


# ---------- Orders / trades ----------

def list_my_orders(conn, user_id: str) -> list:
    rows = conn.execute(
        "SELECT * FROM orders WHERE user_id = ? ORDER BY requested_at DESC LIMIT 200", (user_id,)
    ).fetchall()
    return [dict(r) for r in rows]
