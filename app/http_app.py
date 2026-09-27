"""
app/http_app.py
------------------
Thin WSGI adapter over the service functions in app/auth.py,
app/customer.py, app/admin.py. All business logic lives in those
modules and is unit-tested independently of HTTP; this file only
does request parsing, routing, cookies, and JSON responses.

This is deliberately stdlib-only (see README's "Framework choice"
section for why) so it can actually run and be tested in any Python
3 environment with zero installs beyond cryptography/itsdangerous.
Swapping this file for FastAPI later is a routing-layer rewrite only -
app/auth.py, app/customer.py, app/admin.py, core/*, workers/* do not
need to change.
"""

import json
import re
from http import cookies as http_cookies

from app import admin as admin_svc
from app import auth as auth_svc
from app import customer as customer_svc
from config import settings
from database.db import get_conn

_ROUTES = []


def route(method: str, pattern: str):
    compiled = re.compile("^" + pattern + "$")

    def decorator(fn):
        _ROUTES.append((method, compiled, fn))
        return fn
    return decorator


class HttpError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status
        self.message = message


def _json_response(start_response, status: int, payload: dict, set_cookie: str = None):
    body = json.dumps(payload).encode()
    headers = [("Content-Type", "application/json"), ("Content-Length", str(len(body)))]
    if set_cookie:
        headers.append(("Set-Cookie", set_cookie))
    status_line = f"{status} {'OK' if status < 400 else 'ERROR'}"
    start_response(status_line, headers)
    return [body]


def _read_json_body(environ) -> dict:
    try:
        length = int(environ.get("CONTENT_LENGTH") or 0)
    except ValueError:
        length = 0
    if length == 0:
        return {}
    raw = environ["wsgi.input"].read(length)
    try:
        return json.loads(raw.decode())
    except json.JSONDecodeError:
        raise HttpError("Invalid JSON body", 400)


def _get_cookie(environ, name: str):
    header = environ.get("HTTP_COOKIE", "")
    jar = http_cookies.SimpleCookie()
    jar.load(header)
    if name in jar:
        return jar[name].value
    return None


def _set_cookie_header(name: str, value: str) -> str:
    jar = http_cookies.SimpleCookie()
    jar[name] = value
    jar[name]["path"] = "/"
    jar[name]["httponly"] = True
    if settings.IS_PRODUCTION:
        jar[name]["secure"] = True
    return jar[name].OutputString()


def _require_user(environ, conn) -> dict:
    token = _get_cookie(environ, "session_token")
    user = auth_svc.current_user(conn, token)
    if not user:
        raise HttpError("Not authenticated", 401)
    return user


def _require_admin(environ, conn) -> dict:
    user = _require_user(environ, conn)
    if user["role"] != "admin":
        raise HttpError("Admin access required", 403)
    return user


# ---------------- Auth routes ----------------

@route("POST", r"/auth/register")
def _register(environ, conn, match):
    body = _read_json_body(environ)
    result = auth_svc.register(conn, body.get("email", ""), body.get("password", ""))
    cookie = _set_cookie_header("session_token", result["token"])
    return 201, {"id": result["id"], "email": result["email"]}, cookie


@route("POST", r"/auth/login")
def _login(environ, conn, match):
    body = _read_json_body(environ)
    result = auth_svc.login(conn, body.get("email", ""), body.get("password", ""))
    cookie = _set_cookie_header("session_token", result["token"])
    return 200, {"id": result["id"], "email": result["email"], "role": result["role"]}, cookie


@route("GET", r"/auth/me")
def _me(environ, conn, match):
    user = _require_user(environ, conn)
    return 200, {"id": user["id"], "email": user["email"], "role": user["role"]}, None


@route("POST", r"/auth/logout")
def _logout(environ, conn, match):
    user = _require_user(environ, conn)
    auth_svc.logout(conn, user["id"])
    cookie = _set_cookie_header("session_token", "")
    return 200, {"ok": True}, cookie


# ---------------- Customer routes ----------------

@route("GET", r"/customer/status")
def _customer_status(environ, conn, match):
    user = _require_user(environ, conn)
    return 200, customer_svc.get_status(conn, user["id"]), None


@route("POST", r"/customer/mt5")
def _customer_mt5(environ, conn, match):
    user = _require_user(environ, conn)
    body = _read_json_body(environ)
    result = customer_svc.add_or_update_mt5_account(conn, user["id"], body.get("login"), body.get("password"), body.get("server"))
    return 200, result, None


@route("POST", r"/customer/mt5/test")
def _customer_mt5_test(environ, conn, match):
    user = _require_user(environ, conn)
    result = customer_svc.test_mt5_connection(conn, user["id"])
    return 200, result, None


@route("POST", r"/customer/settings")
def _customer_settings(environ, conn, match):
    user = _require_user(environ, conn)
    body = _read_json_body(environ)
    result = customer_svc.update_risk_settings(
        conn, user["id"],
        fixed_lot=body.get("fixed_lot"), max_open_trades=body.get("max_open_trades"),
        max_daily_loss=body.get("max_daily_loss", customer_svc._UNSET),
        max_drawdown_percent=body.get("max_drawdown_percent", customer_svc._UNSET),
    )
    return 200, result, None


@route("POST", r"/customer/copy-toggle")
def _customer_copy_toggle(environ, conn, match):
    user = _require_user(environ, conn)
    body = _read_json_body(environ)
    customer_svc.set_copy_enabled(conn, user["id"], bool(body.get("enabled")))
    return 200, {"copy_enabled": bool(body.get("enabled"))}, None


@route("POST", r"/customer/payments")
def _customer_submit_payment(environ, conn, match):
    user = _require_user(environ, conn)
    body = _read_json_body(environ)
    result = customer_svc.submit_payment(
        conn, user["id"], body.get("method"), body.get("claimed_amount"),
        body.get("receipt_filename"), body.get("receipt_b64"),
    )
    return 201, result, None


@route("GET", r"/customer/payments")
def _customer_list_payments(environ, conn, match):
    user = _require_user(environ, conn)
    return 200, {"payments": customer_svc.list_my_payments(conn, user["id"])}, None


@route("GET", r"/customer/orders")
def _customer_orders(environ, conn, match):
    user = _require_user(environ, conn)
    return 200, {"orders": customer_svc.list_my_orders(conn, user["id"])}, None


# ---------------- Admin routes ----------------

@route("GET", r"/admin/customers")
def _admin_customers(environ, conn, match):
    _require_admin(environ, conn)
    return 200, {"customers": admin_svc.list_customers(conn)}, None


@route("POST", r"/admin/customers/(?P<customer_id>[^/]+)/active")
def _admin_set_active(environ, conn, match):
    admin = _require_admin(environ, conn)
    body = _read_json_body(environ)
    admin_svc.set_customer_active(conn, admin["id"], match.group("customer_id"), bool(body.get("active")))
    return 200, {"ok": True}, None


@route("GET", r"/admin/payments/pending")
def _admin_pending_payments(environ, conn, match):
    _require_admin(environ, conn)
    return 200, {"payments": admin_svc.list_pending_payments(conn)}, None


@route("POST", r"/admin/payments/(?P<payment_id>[^/]+)/approve")
def _admin_approve(environ, conn, match):
    admin = _require_admin(environ, conn)
    result = admin_svc.approve_payment(conn, admin["id"], match.group("payment_id"), settings.CHALLENGE_DURATION_DAYS)
    return 200, result, None


@route("POST", r"/admin/payments/(?P<payment_id>[^/]+)/reject")
def _admin_reject(environ, conn, match):
    admin = _require_admin(environ, conn)
    body = _read_json_body(environ)
    result = admin_svc.reject_payment(conn, admin["id"], match.group("payment_id"), body.get("reason", ""))
    return 200, result, None


@route("POST", r"/admin/customers/(?P<customer_id>[^/]+)/activate")
def _admin_manual_activate(environ, conn, match):
    admin = _require_admin(environ, conn)
    body = _read_json_body(environ)
    days = int(body.get("days", settings.CHALLENGE_DURATION_DAYS))
    result = admin_svc.manually_activate_access(conn, admin["id"], match.group("customer_id"), days)
    return 200, result, None


@route("GET", r"/admin/trading/overview")
def _admin_trading_overview(environ, conn, match):
    _require_admin(environ, conn)
    return 200, admin_svc.trading_overview(conn), None


@route("POST", r"/admin/emergency-stop")
def _admin_emergency_stop(environ, conn, match):
    admin = _require_admin(environ, conn)
    body = _read_json_body(environ)
    admin_svc.set_emergency_stop(conn, admin["id"], bool(body.get("active")))
    return 200, {"emergency_stop": bool(body.get("active"))}, None


@route("GET", r"/admin/system/health")
def _admin_system_health(environ, conn, match):
    _require_admin(environ, conn)
    return 200, admin_svc.system_health(conn), None


@route("GET", r"/health")
def _health(environ, conn, match):
    return 200, {"status": "ok"}, None


# ---------------- WSGI entrypoint ----------------

def application(environ, start_response):
    method = environ["REQUEST_METHOD"]
    path = environ["PATH_INFO"]
    conn = get_conn()

    for route_method, pattern, handler in _ROUTES:
        if route_method != method:
            continue
        m = pattern.match(path)
        if not m:
            continue
        try:
            status, payload, cookie = handler(environ, conn, m)
            return _json_response(start_response, status, payload, cookie)
        except HttpError as e:
            return _json_response(start_response, e.status, {"error": e.message})
        except (auth_svc.AuthError, customer_svc.CustomerError, admin_svc.AdminError) as e:
            return _json_response(start_response, e.status, {"error": str(e)})
        except Exception as e:  # noqa: BLE001 - last resort, never leak internals
            return _json_response(start_response, 500, {"error": "internal error", "detail": str(e) if not settings.IS_PRODUCTION else None})

    return _json_response(start_response, 404, {"error": "not found"})
