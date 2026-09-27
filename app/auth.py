"""
app/auth.py
--------------
Register / login / logout / current-user, as plain functions over a
DB connection - no HTTP concerns here, so these are directly unit
testable (see tests/test_auth.py) and reusable if the HTTP layer is
later swapped for FastAPI.
"""

import time
import uuid
from typing import Optional

from security.passwords import hash_password, verify_password
from security.tokens import create_session_token, verify_session_token


class AuthError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _audit(conn, actor_user_id, action, target_user_id=None, detail=None):
    conn.execute(
        "INSERT INTO audit_events (id, actor_user_id, action, target_user_id, detail, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (uuid.uuid4().hex, actor_user_id, action, target_user_id, detail, time.strftime("%Y-%m-%dT%H:%M:%S")),
    )


def register(conn, email: str, password: str) -> dict:
    email = email.strip().lower()
    if not email or "@" not in email:
        raise AuthError("A valid email is required")
    if len(password) < 10:
        raise AuthError("Password must be at least 10 characters")

    existing = conn.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone()
    if existing:
        raise AuthError("An account with this email already exists", status=409)

    user_id = uuid.uuid4().hex
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    conn.execute(
        "INSERT INTO users (id, email, password_hash, role, is_active, created_at) VALUES (?, ?, ?, 'customer', 1, ?)",
        (user_id, email, hash_password(password), now),
    )
    conn.execute(
        "INSERT INTO customer_settings (user_id, copy_enabled, provider_enabled, fixed_lot, max_open_trades, updated_at) "
        "VALUES (?, 0, 1, 0.01, 5, ?)",
        (user_id, now),
    )
    conn.execute(
        "INSERT INTO access (id, user_id, status, created_at) VALUES (?, ?, 'expired', ?)",
        (uuid.uuid4().hex, user_id, now),
    )
    _audit(conn, user_id, "register")
    conn.commit()

    token = create_session_token(user_id)
    return {"id": user_id, "email": email, "token": token}


def login(conn, email: str, password: str) -> dict:
    email = email.strip().lower()
    row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    # Same error for "no such user" and "wrong password" - don't leak which one.
    if not row or not verify_password(password, row["password_hash"]):
        raise AuthError("Invalid email or password", status=401)
    if not row["is_active"]:
        raise AuthError("This account has been disabled", status=403)

    _audit(conn, row["id"], "login")
    conn.commit()

    token = create_session_token(row["id"])
    return {"id": row["id"], "email": row["email"], "role": row["role"], "token": token}


def logout(conn, user_id: str):
    _audit(conn, user_id, "logout")
    conn.commit()


def change_password(conn, user_id: str, current_password: str, new_password: str) -> None:
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row:
        raise AuthError("Not authenticated", status=401)
    if not verify_password(current_password, row["password_hash"]):
        raise AuthError("Current password is incorrect", status=401)
    if len(new_password) < 10:
        raise AuthError("New password must be at least 10 characters")

    conn.execute(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (hash_password(new_password), user_id),
    )
    _audit(conn, user_id, "change_password")
    conn.commit()


def current_user(conn, token: Optional[str]) -> Optional[dict]:
    if not token:
        return None
    user_id = verify_session_token(token)
    if not user_id:
        return None
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row or not row["is_active"]:
        return None
    return dict(row)
