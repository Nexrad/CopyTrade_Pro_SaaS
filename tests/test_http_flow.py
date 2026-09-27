import tests._bootstrap  # noqa: F401

import json
import threading
import unittest
import urllib.error
import urllib.request
from wsgiref.simple_server import make_server

from app.http_app import application
from database.db import reset_db_for_tests


class _CookieTrackingOpener:
    """Tiny stand-in for a browser's cookie jar - stores the Set-Cookie
    value from each response and replays it on subsequent requests."""

    def __init__(self, base_url):
        self.base_url = base_url
        self.cookie = None

    def request(self, method, path, body=None):
        url = self.base_url + path
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if self.cookie:
            req.add_header("Cookie", self.cookie)
        try:
            resp = urllib.request.urlopen(req, timeout=5)
            status = resp.status
            payload = json.loads(resp.read().decode())
            set_cookie = resp.headers.get("Set-Cookie")
        except urllib.error.HTTPError as e:
            status = e.code
            payload = json.loads(e.read().decode())
            set_cookie = e.headers.get("Set-Cookie")
        if set_cookie:
            self.cookie = set_cookie.split(";")[0]
        return status, payload


class TestHttpEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reset_db_for_tests()
        cls.httpd = make_server("127.0.0.1", 0, application)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def _client(self):
        return _CookieTrackingOpener(f"http://127.0.0.1:{self.port}")

    def test_health(self):
        status, payload = self._client().request("GET", "/health")
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ok")

    def test_register_login_me_logout(self):
        c = self._client()

        status, payload = c.request("POST", "/auth/register", {"email": "http1@example.com", "password": "StrongPassword123"})
        self.assertEqual(status, 201)
        self.assertEqual(payload["email"], "http1@example.com")

        status, payload = c.request("GET", "/auth/me")
        self.assertEqual(status, 200)
        self.assertEqual(payload["role"], "customer")

        status, payload = c.request("POST", "/auth/logout")
        self.assertEqual(status, 200)

        status, payload = c.request("GET", "/auth/me")
        self.assertEqual(status, 401)

        status, payload = c.request("POST", "/auth/login", {"email": "http1@example.com", "password": "StrongPassword123"})
        self.assertEqual(status, 200)

    def test_customer_cannot_reach_admin_routes(self):
        c = self._client()
        c.request("POST", "/auth/register", {"email": "http2@example.com", "password": "StrongPassword123"})
        status, payload = c.request("GET", "/admin/customers")
        self.assertEqual(status, 403)

    def test_unauthenticated_cannot_reach_customer_routes(self):
        c = self._client()
        status, payload = c.request("GET", "/customer/status")
        self.assertEqual(status, 401)

    def test_customer_full_journey(self):
        c = self._client()
        c.request("POST", "/auth/register", {"email": "http3@example.com", "password": "StrongPassword123"})

        status, payload = c.request("POST", "/customer/mt5", {"login": "1001", "password": "brokerpw", "server": "Srv"})
        self.assertEqual(status, 200)
        self.assertNotIn("password", payload)  # never echoed back

        status, payload = c.request("POST", "/customer/mt5/test")
        self.assertEqual(status, 200)
        self.assertTrue(payload["connected"])

        status, payload = c.request("POST", "/customer/settings", {"fixed_lot": 0.02})
        self.assertEqual(status, 200)
        self.assertEqual(payload["fixed_lot"], 0.02)

        status, payload = c.request("GET", "/customer/status")
        self.assertEqual(status, 200)
        self.assertEqual(payload["mt5_account"]["login"], "1001")

    def test_change_password_http(self):
        c = self._client()
        c.request("POST", "/auth/register", {"email": "http4@example.com", "password": "StrongPassword123"})

        status, payload = c.request(
            "POST",
            "/auth/change-password",
            {"current_password": "WrongPassword999", "new_password": "NewStrongPassword456"},
        )
        self.assertEqual(status, 401)

        status, payload = c.request(
            "POST",
            "/auth/change-password",
            {"current_password": "StrongPassword123", "new_password": "NewStrongPassword456"},
        )
        self.assertEqual(status, 200)

        c.request("POST", "/auth/logout")
        status, payload = c.request(
            "POST", "/auth/login", {"email": "http4@example.com", "password": "NewStrongPassword456"}
        )
        self.assertEqual(status, 200)

    def test_change_password_requires_auth(self):
        c = self._client()
        status, payload = c.request(
            "POST", "/auth/change-password", {"current_password": "a", "new_password": "NewStrongPassword456"}
        )
        self.assertEqual(status, 401)

    def test_payment_info_http(self):
        c = self._client()
        c.request("POST", "/auth/register", {"email": "http5@example.com", "password": "StrongPassword123"})

        status, payload = c.request("GET", "/customer/payment-info")
        self.assertEqual(status, 200)
        self.assertIn("challenge_price", payload)
        self.assertIn("payment_instructions", payload)
        self.assertEqual(set(payload["methods"]), {"telebirr", "cbe"})

    def test_payment_info_requires_auth(self):
        c = self._client()
        status, payload = c.request("GET", "/customer/payment-info")
        self.assertEqual(status, 401)

    def test_provider_toggle_http(self):
        c = self._client()
        c.request("POST", "/auth/register", {"email": "http6@example.com", "password": "StrongPassword123"})

        status, payload = c.request("POST", "/customer/provider-toggle", {"enabled": False})
        self.assertEqual(status, 200)
        self.assertFalse(payload["provider_enabled"])

        status, payload = c.request("GET", "/customer/status")
        self.assertEqual(status, 200)
        self.assertEqual(payload["settings"]["provider_enabled"], 0)

    def test_admin_can_reach_admin_routes(self):
        c = self._client()
        status, payload = c.request(
            "POST", "/auth/register", {"email": "httpadmin@example.com", "password": "StrongPassword123"}
        )
        # Promote directly in the DB, mirroring how a real admin account is provisioned.
        from database.db import get_conn

        conn = get_conn()
        conn.execute("UPDATE users SET role='admin' WHERE id=?", (payload["id"],))
        conn.commit()

        status, payload = c.request("GET", "/admin/customers")
        self.assertEqual(status, 200)
        self.assertIn("customers", payload)

        status, payload = c.request("GET", "/admin/system/health")
        self.assertEqual(status, 200)

        status, payload = c.request("GET", "/admin/trading/overview")
        self.assertEqual(status, 200)
        self.assertIn("open_trades", payload)
        self.assertIn("active_customers", payload)


if __name__ == "__main__":
    unittest.main()
