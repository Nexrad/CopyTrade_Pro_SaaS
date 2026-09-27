import tests._bootstrap  # noqa: F401

import base64
import unittest

from app import admin as admin_svc
from app import auth as auth_svc
from app import customer as customer_svc
from core.signal_engine import handle_incoming_message
from database.db import get_conn, reset_db_for_tests
from workers.worker_manager import manager as worker_manager


def _ensure_admin(conn):
    row = conn.execute("SELECT id FROM users WHERE role='admin' LIMIT 1").fetchone()
    if row:
        return row["id"]
    reg = auth_svc.register(conn, "admin@example.com", "StrongPassword123")
    conn.execute("UPDATE users SET role='admin' WHERE id=?", (reg["id"],))
    conn.commit()
    return reg["id"]


def _onboard_active_customer(conn, email, lot=0.01):
    reg = auth_svc.register(conn, email, "StrongPassword123")
    customer_svc.add_or_update_mt5_account(conn, reg["id"], "1001", "brokerpw", "BrokerServer")
    customer_svc.test_mt5_connection(conn, reg["id"])  # connects the DryRunExecutor
    customer_svc.set_copy_enabled(conn, reg["id"], True)
    customer_svc.update_risk_settings(conn, reg["id"], fixed_lot=lot)

    receipt = base64.b64encode(b"fake receipt").decode()
    payment = customer_svc.submit_payment(conn, reg["id"], "telebirr", 100, "r.jpg", receipt)
    admin_svc.approve_payment(conn, _ensure_admin(conn), payment["id"], challenge_duration_days=30)
    return reg["id"]


class TestSignalEngine(unittest.TestCase):
    def setUp(self):
        self.conn = get_conn()
        reset_db_for_tests()
        worker_manager._workers.clear()  # fresh workers between tests

    def test_non_signal_message_is_ignored(self):
        result = handle_incoming_message(get_conn, "TP1 smashed, great pips!")
        self.assertFalse(result["parsed"])

    def test_signal_is_parsed_once_and_fanned_out_to_all_eligible_customers(self):
        _onboard_active_customer(self.conn, "fanout1@example.com")
        _onboard_active_customer(self.conn, "fanout2@example.com")
        _onboard_active_customer(self.conn, "fanout3@example.com")

        result = handle_incoming_message(get_conn, "GOLD sell now\nSL 4554\nTP 4400")

        self.assertTrue(result["parsed"])
        self.assertFalse(result["duplicate"])
        self.assertEqual(len(result["results"]), 3)
        self.assertTrue(all(r["status"] == "filled" for r in result["results"]))

    def test_duplicate_within_window_is_not_reprocessed(self):
        _onboard_active_customer(self.conn, "dup1@example.com")
        first = handle_incoming_message(get_conn, "GOLD sell now\nSL 4554\nTP 4400")
        second = handle_incoming_message(get_conn, "GOLD sell now\nSL 4554\nTP 4400")

        self.assertFalse(first["duplicate"])
        self.assertTrue(second["duplicate"])

        orders = customer_svc.list_my_orders(self.conn, list(worker_manager._workers.keys())[0])
        self.assertEqual(len(orders), 1)  # only the first message produced an order

    def test_customer_with_copy_disabled_is_skipped(self):
        active_id = _onboard_active_customer(self.conn, "active_copy@example.com")
        disabled_id = _onboard_active_customer(self.conn, "disabled_copy@example.com")
        customer_svc.set_copy_enabled(self.conn, disabled_id, False)

        result = handle_incoming_message(get_conn, "GOLD sell now\nSL 4554\nTP 4400")
        by_user = {r["user_id"]: r for r in result["results"]}

        self.assertEqual(by_user[active_id]["status"], "filled")
        self.assertEqual(by_user[disabled_id]["status"], "rejected")
        self.assertIn("copy trading is turned off", by_user[disabled_id]["reason"])

    def test_one_customer_failure_does_not_block_another(self):
        good_id = _onboard_active_customer(self.conn, "good@example.com")
        # Simulate a broken worker for this customer without touching the good one.
        broken_id = _onboard_active_customer(self.conn, "broken@example.com")
        broken_worker = worker_manager.get_or_create(broken_id)
        broken_worker.executor = None  # will raise when .place_order is called

        result = handle_incoming_message(get_conn, "GOLD sell now\nSL 4554\nTP 4400")
        by_user = {r["user_id"]: r for r in result["results"]}

        self.assertEqual(by_user[good_id]["status"], "filled")
        self.assertEqual(by_user[broken_id]["status"], "error")  # caught, not raised

    def test_expired_access_is_not_traded(self):
        reg = auth_svc.register(self.conn, "expired@example.com", "StrongPassword123")
        customer_svc.add_or_update_mt5_account(self.conn, reg["id"], "1001", "pw", "Server")
        customer_svc.test_mt5_connection(self.conn, reg["id"])
        customer_svc.set_copy_enabled(self.conn, reg["id"], True)
        # No payment approved -> access stays 'expired' (the register() default).

        result = handle_incoming_message(get_conn, "GOLD sell now\nSL 4554\nTP 4400")
        self.assertEqual(result["results"][0]["status"], "rejected")
        self.assertIn("access", result["results"][0]["reason"])


if __name__ == "__main__":
    unittest.main()
