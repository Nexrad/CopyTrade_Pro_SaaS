import tests._bootstrap  # noqa: F401

import unittest

from app import admin as admin_svc
from app import auth as auth_svc
from app import customer as customer_svc
from database.db import get_conn, reset_db_for_tests


class TestAuthFlow(unittest.TestCase):
    def setUp(self):
        self.conn = get_conn()
        reset_db_for_tests()

    def test_register_then_login(self):
        reg = auth_svc.register(self.conn, "alice@example.com", "StrongPassword123")
        self.assertTrue(reg["token"])

        login = auth_svc.login(self.conn, "alice@example.com", "StrongPassword123")
        self.assertEqual(login["email"], "alice@example.com")

    def test_duplicate_email_rejected(self):
        auth_svc.register(self.conn, "bob@example.com", "StrongPassword123")
        with self.assertRaises(auth_svc.AuthError):
            auth_svc.register(self.conn, "bob@example.com", "AnotherPassword456")

    def test_wrong_password_rejected(self):
        auth_svc.register(self.conn, "carol@example.com", "StrongPassword123")
        with self.assertRaises(auth_svc.AuthError):
            auth_svc.login(self.conn, "carol@example.com", "WrongPassword")

    def test_disabled_user_cannot_login(self):
        reg = auth_svc.register(self.conn, "dave@example.com", "StrongPassword123")
        self.conn.execute("UPDATE users SET is_active=0 WHERE id=?", (reg["id"],))
        self.conn.commit()
        with self.assertRaises(auth_svc.AuthError):
            auth_svc.login(self.conn, "dave@example.com", "StrongPassword123")

    def test_session_token_resolves_to_user(self):
        reg = auth_svc.register(self.conn, "erin@example.com", "StrongPassword123")
        user = auth_svc.current_user(self.conn, reg["token"])
        self.assertEqual(user["email"], "erin@example.com")

    def test_invalid_token_resolves_to_none(self):
        self.assertIsNone(auth_svc.current_user(self.conn, "garbage-token"))

    def test_change_password_then_login_with_new_password(self):
        reg = auth_svc.register(self.conn, "frank@example.com", "StrongPassword123")
        auth_svc.change_password(self.conn, reg["id"], "StrongPassword123", "EvenStrongerPassword456")

        with self.assertRaises(auth_svc.AuthError):
            auth_svc.login(self.conn, "frank@example.com", "StrongPassword123")

        login = auth_svc.login(self.conn, "frank@example.com", "EvenStrongerPassword456")
        self.assertEqual(login["email"], "frank@example.com")

    def test_change_password_rejects_wrong_current_password(self):
        reg = auth_svc.register(self.conn, "grace@example.com", "StrongPassword123")
        with self.assertRaises(auth_svc.AuthError):
            auth_svc.change_password(self.conn, reg["id"], "TotallyWrongPassword", "EvenStrongerPassword456")
        # original password must still work
        auth_svc.login(self.conn, "grace@example.com", "StrongPassword123")

    def test_change_password_rejects_short_new_password(self):
        reg = auth_svc.register(self.conn, "heidi@example.com", "StrongPassword123")
        with self.assertRaises(auth_svc.AuthError):
            auth_svc.change_password(self.conn, reg["id"], "StrongPassword123", "short")


class TestCustomerIsolation(unittest.TestCase):
    """Customer A must never see or affect Customer B's data (spec section 16)."""

    def setUp(self):
        self.conn = get_conn()
        reset_db_for_tests()
        self.alice = auth_svc.register(self.conn, "alice2@example.com", "StrongPassword123")
        self.bob = auth_svc.register(self.conn, "bob2@example.com", "StrongPassword123")

    def test_mt5_accounts_are_isolated(self):
        customer_svc.add_or_update_mt5_account(self.conn, self.alice["id"], "1001", "alicepw", "BrokerServer")
        customer_svc.add_or_update_mt5_account(self.conn, self.bob["id"], "2002", "bobpw", "BrokerServer")

        alice_status = customer_svc.get_status(self.conn, self.alice["id"])
        bob_status = customer_svc.get_status(self.conn, self.bob["id"])

        self.assertEqual(alice_status["mt5_account"]["login"], "1001")
        self.assertEqual(bob_status["mt5_account"]["login"], "2002")
        self.assertNotEqual(alice_status["mt5_account"]["id"], bob_status["mt5_account"]["id"])

    def test_payment_receipts_are_isolated(self):
        import base64
        receipt = base64.b64encode(b"fake receipt bytes").decode()
        payment = customer_svc.submit_payment(self.conn, self.alice["id"], "telebirr", 500, "receipt.jpg", receipt)

        # Bob must not be able to fetch Alice's receipt through his own lookup.
        with self.assertRaises(customer_svc.CustomerError):
            customer_svc.get_receipt_path_for_owner(self.conn, self.bob["id"], payment["id"])

        # Alice can fetch her own.
        path = customer_svc.get_receipt_path_for_owner(self.conn, self.alice["id"], payment["id"])
        self.assertTrue(path.endswith("receipt.jpg"))

    def test_risk_settings_are_isolated(self):
        customer_svc.update_risk_settings(self.conn, self.alice["id"], fixed_lot=0.05)
        alice_settings = customer_svc.get_status(self.conn, self.alice["id"])["settings"]
        bob_settings = customer_svc.get_status(self.conn, self.bob["id"])["settings"]
        self.assertEqual(alice_settings["fixed_lot"], 0.05)
        self.assertEqual(bob_settings["fixed_lot"], 0.01)  # untouched default


class TestAdminAuthorization(unittest.TestCase):
    def setUp(self):
        self.conn = get_conn()
        reset_db_for_tests()
        self.customer = auth_svc.register(self.conn, "plain@example.com", "StrongPassword123")
        # A real admin user, not a magic string - the FK from access/payments/
        # audit_events to users.id is enforced for real, so tests must honor it.
        admin_reg = auth_svc.register(self.conn, "admin@example.com", "StrongPassword123")
        self.conn.execute("UPDATE users SET role='admin' WHERE id=?", (admin_reg["id"],))
        self.conn.commit()
        self.admin_id = admin_reg["id"]

    def test_plain_customer_is_not_admin(self):
        user = auth_svc.current_user(self.conn, self.customer["token"])
        self.assertEqual(user["role"], "customer")
        # This mirrors what app/http_app.py's _require_admin enforces.
        self.assertNotEqual(user["role"], "admin")

    def test_payment_approval_activates_access(self):
        import base64
        receipt = base64.b64encode(b"fake receipt").decode()
        payment = customer_svc.submit_payment(self.conn, self.customer["id"], "cbe", 1000, "r.jpg", receipt)

        before = customer_svc.get_status(self.conn, self.customer["id"])["access"]
        self.assertEqual(before["status"], "expired")

        admin_svc.approve_payment(self.conn, self.admin_id, payment["id"], challenge_duration_days=30)

        after = customer_svc.get_status(self.conn, self.customer["id"])["access"]
        self.assertEqual(after["status"], "active")
        self.assertIsNotNone(after["access_end"])

    def test_rejected_payment_does_not_activate_access(self):
        import base64
        receipt = base64.b64encode(b"fake receipt").decode()
        payment = customer_svc.submit_payment(self.conn, self.customer["id"], "cbe", 1000, "r.jpg", receipt)
        admin_svc.reject_payment(self.conn, self.admin_id, payment["id"], "Amount does not match")

        status = customer_svc.get_status(self.conn, self.customer["id"])["access"]
        self.assertEqual(status["status"], "expired")

        payments = customer_svc.list_my_payments(self.conn, self.customer["id"])
        self.assertEqual(payments[0]["status"], "rejected")
        self.assertEqual(payments[0]["rejection_reason"], "Amount does not match")


if __name__ == "__main__":
    unittest.main()
