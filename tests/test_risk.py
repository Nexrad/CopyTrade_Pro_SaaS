import tests._bootstrap  # noqa: F401

import unittest

from core import risk


def _base_kwargs(**overrides):
    kwargs = dict(
        user_is_active=True, access_status="active", copy_enabled=True,
        provider_enabled=True, mt5_connected=True, global_emergency_stop=False,
        open_trades_count=0, max_open_trades=5,
        daily_loss_so_far=0.0, max_daily_loss=None,
        drawdown_percent_so_far=0.0, max_drawdown_percent=None,
        lot_size=0.01, symbol="XAUUSDm",
    )
    kwargs.update(overrides)
    return kwargs


class TestRiskEngine(unittest.TestCase):
    def test_allows_when_everything_fine(self):
        self.assertTrue(risk.evaluate(**_base_kwargs()).allowed)

    def test_null_daily_loss_limit_never_blocks(self):
        # The critical nullable-limit case from the spec: NULL means
        # "no limit", never "limit of zero".
        decision = risk.evaluate(**_base_kwargs(daily_loss_so_far=99999.0, max_daily_loss=None))
        self.assertTrue(decision.allowed)

    def test_real_daily_loss_limit_blocks_when_exceeded(self):
        decision = risk.evaluate(**_base_kwargs(daily_loss_so_far=100.0, max_daily_loss=50.0))
        self.assertFalse(decision.allowed)
        self.assertIn("daily loss", decision.reason)

    def test_emergency_stop_blocks_everything(self):
        decision = risk.evaluate(**_base_kwargs(global_emergency_stop=True))
        self.assertFalse(decision.allowed)

    def test_expired_access_blocks(self):
        decision = risk.evaluate(**_base_kwargs(access_status="expired"))
        self.assertFalse(decision.allowed)

    def test_copy_disabled_blocks(self):
        decision = risk.evaluate(**_base_kwargs(copy_enabled=False))
        self.assertFalse(decision.allowed)

    def test_max_open_trades_blocks(self):
        decision = risk.evaluate(**_base_kwargs(open_trades_count=5, max_open_trades=5))
        self.assertFalse(decision.allowed)

    def test_disconnected_mt5_blocks(self):
        decision = risk.evaluate(**_base_kwargs(mt5_connected=False))
        self.assertFalse(decision.allowed)


if __name__ == "__main__":
    unittest.main()
