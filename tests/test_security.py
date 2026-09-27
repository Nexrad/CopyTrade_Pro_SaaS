import tests._bootstrap  # noqa: F401  (must run before any project import below)

import unittest

from security import encryption, passwords, tokens


class TestPasswords(unittest.TestCase):
    def test_hash_and_verify_roundtrip(self):
        h = passwords.hash_password("CorrectHorseBattery1")
        self.assertTrue(passwords.verify_password("CorrectHorseBattery1", h))

    def test_wrong_password_rejected(self):
        h = passwords.hash_password("CorrectHorseBattery1")
        self.assertFalse(passwords.verify_password("wrong-password", h))

    def test_hashes_are_salted_differently(self):
        h1 = passwords.hash_password("SamePassword123")
        h2 = passwords.hash_password("SamePassword123")
        self.assertNotEqual(h1, h2)


class TestEncryption(unittest.TestCase):
    def test_mt5_password_roundtrip(self):
        ct = encryption.encrypt("MyRealMt5Password")
        self.assertNotEqual(ct, "MyRealMt5Password")
        self.assertEqual(encryption.decrypt(ct), "MyRealMt5Password")


class TestTokens(unittest.TestCase):
    def test_token_verifies(self):
        t = tokens.create_session_token("user-123")
        self.assertEqual(tokens.verify_session_token(t), "user-123")

    def test_tampered_token_rejected(self):
        t = tokens.create_session_token("user-123")
        self.assertIsNone(tokens.verify_session_token(t + "x"))


if __name__ == "__main__":
    unittest.main()
