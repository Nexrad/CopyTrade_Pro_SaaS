import tests._bootstrap  # noqa: F401

import unittest

from core.providers.marshallfx import AbMarshallProvider


class TestAbMarshallProvider(unittest.TestCase):
    def setUp(self):
        self.provider = AbMarshallProvider()

    def test_market_order_signal(self):
        text = "GOLD sell now\nSL 4554\nTP 4400"
        signal = self.provider.parse(text)
        self.assertIsNotNone(signal)
        self.assertEqual(signal.direction, "SELL")
        self.assertEqual(signal.symbol, "XAUUSDm")
        self.assertEqual(signal.sl, 4554.0)
        self.assertEqual(signal.tp, 4400.0)
        self.assertIsNone(signal.entry_min)  # market order - no price stated

    def test_signal_with_explicit_entry_price(self):
        text = "GOLD sell again 4077\nSL 4090\nTP 4000"
        signal = self.provider.parse(text)
        self.assertIsNotNone(signal)
        self.assertEqual(signal.entry_min, 4077.0)

    def test_status_update_is_not_a_signal(self):
        text = "TP1 smashed 100 pips guys!"
        self.assertIsNone(self.provider.parse(text))

    def test_sl_move_is_not_a_new_signal(self):
        text = "Move SL to 4043 just in case"
        # Has "SL" and a number but no direction word - must not be treated as an entry.
        self.assertIsNone(self.provider.parse(text))

    def test_direction_without_sl_is_not_a_signal(self):
        text = "GOLD buy now, more info soon"
        self.assertIsNone(self.provider.parse(text))


if __name__ == "__main__":
    unittest.main()
