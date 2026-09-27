"""
app/admin.py
--------------
Admin-only operations (product spec section 10). Every function here
must ONLY be reachable through a route that has already verified
role == 'admin' (see app/http_app.py's require_admin) - these
functions themselves don't re-check the role, by design, so that
never happens twice in two different places and drifts apart.
"""

import time
import uuid
from typing import Optional

from app.auth import _audit


class AdminError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


# ---------- Customers ----------

def list_customers(conn, search: Optional[str] = None) -> list:
    query = """
        SELECT u.id, u.email, u.is_active, u.created_at,
               a.status AS access_status, a.access_end,
               m.connected AS mt5_connected,
               cs.copy_enabled
        FROM users u
        LEFT JOIN access a ON a.user_id = u.id AND a.status = 'active'
        LEFT JOIN mt5_accounts m ON m.user_id = u.id
        LEFT JOIN customer_settings cs ON cs.user_id = u.id
        WHERE u.role = 'customer'
    """
    params = []
    if search:
        query += " AND u.email LIKE ?"
        params.append(f"%{search}%")
    query += " ORDER BY u.created_at DESC"
    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def set_customer_active(conn, admin_id: str, customer_id: str, active: bool):
    conn.execute("UPDATE users SET is_active=? WHERE id=? AND role='customer'", (1 if active else 0, customer_id))
    _audit(conn, admin_id, "set_customer_active", target_user_id=customer_id, detail=str(active))
    conn.commit()


# ---------- Payments ----------

def list_pending_payments(conn) -> list:
    rows = conn.execute("""
        SELECT p.*, u.email FROM payments p JOIN users u ON u.id = p.user_id
        WHERE p.status = 'pending_review' ORDER BY p.submitted_at ASC
    """).fetchall()
    return [dict(r) for r in rows]


def get_receipt_path_for_admin(conn, payment_id: str) -> str:
    row = conn.execute("SELECT receipt_path FROM payments WHERE id = ?", (payment_id,)).fetchone()
    if not row:
        raise AdminError("Payment not found", status=404)
    return row["receipt_path"]


def approve_payment(conn, admin_id: str, payment_id: str, challenge_duration_days: int) -> dict:
    payment = conn.execute("SELECT * FROM payments WHERE id = ?", (payment_id,)).fetchone()
    if not payment:
        raise AdminError("Payment not found", status=404)
    if payment["status"] != "pending_review":
        raise AdminError("Payment already reviewed", status=409)

    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    end_ts = time.time() + challenge_duration_days * 86400
    end_str = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(end_ts))

    conn.execute(
        "UPDATE payments SET status='approved', reviewed_at=?, reviewed_by=? WHERE id=?",
        (now, admin_id, payment_id),
    )
    # One active access row per approval - old rows are left as history, not deleted.
    conn.execute(
        "INSERT INTO access (id, user_id, status, access_start, access_end, activated_by, payment_id, created_at) "
        "VALUES (?, ?, 'active', ?, ?, ?, ?, ?)",
        (uuid.uuid4().hex, payment["user_id"], now, end_str, admin_id, payment_id, now),
    )
    _audit(conn, admin_id, "approve_payment", target_user_id=payment["user_id"], detail=payment_id)
    conn.commit()
    return {"status": "approved", "access_start": now, "access_end": end_str}


def reject_payment(conn, admin_id: str, payment_id: str, reason: str) -> dict:
    payment = conn.execute("SELECT * FROM payments WHERE id = ?", (payment_id,)).fetchone()
    if not payment:
        raise AdminError("Payment not found", status=404)
    if payment["status"] != "pending_review":
        raise AdminError("Payment already reviewed", status=409)

    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    conn.execute(
        "UPDATE payments SET status='rejected', rejection_reason=?, reviewed_at=?, reviewed_by=? WHERE id=?",
        (reason, now, admin_id, payment_id),
    )
    _audit(conn, admin_id, "reject_payment", target_user_id=payment["user_id"], detail=reason)
    conn.commit()
    return {"status": "rejected", "reason": reason}


def manually_activate_access(conn, admin_id: str, customer_id: str, days: int) -> dict:
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    end_str = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() + days * 86400))
    conn.execute(
        "INSERT INTO access (id, user_id, status, access_start, access_end, activated_by, created_at) "
        "VALUES (?, ?, 'active', ?, ?, ?, ?)",
        (uuid.uuid4().hex, customer_id, now, end_str, admin_id, now),
    )
    _audit(conn, admin_id, "manual_activate_access", target_user_id=customer_id, detail=f"{days} days")
    conn.commit()
    return {"status": "active", "access_start": now, "access_end": end_str}


def expire_stale_access(conn):
    """
    Run periodically (see main.py's background loop): flips access rows
    past access_end from active to expired. Per spec section 9, this
    only stops NEW copying - it never touches existing MT5 positions.
    """
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    conn.execute("UPDATE access SET status='expired' WHERE status='active' AND access_end IS NOT NULL AND access_end < ?", (now,))
    conn.commit()


# ---------- Trading / system ----------

def trading_overview(conn) -> dict:
    open_trades = conn.execute("SELECT COUNT(*) AS c FROM orders WHERE status='filled'").fetchone()["c"]
    active_customers = conn.execute(
        "SELECT COUNT(*) AS c FROM customer_settings WHERE copy_enabled=1"
    ).fetchone()["c"]
    return {"open_trades": open_trades, "active_customers": active_customers}


def set_emergency_stop(conn, admin_id: str, active: bool):
    conn.execute(
        "INSERT INTO runtime_settings (key, value) VALUES ('global_emergency_stop', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        ("1" if active else "0",),
    )
    _audit(conn, admin_id, "set_emergency_stop", detail=str(active))
    conn.commit()


def get_emergency_stop(conn) -> bool:
    row = conn.execute("SELECT value FROM runtime_settings WHERE key='global_emergency_stop'").fetchone()
    return row is not None and row["value"] == "1"


def system_health(conn) -> dict:
    rows = conn.execute(
        "SELECT component, level, message, created_at FROM system_events ORDER BY created_at DESC LIMIT 20"
    ).fetchall()
    return {"recent_events": [dict(r) for r in rows], "emergency_stop": get_emergency_stop(conn)}
