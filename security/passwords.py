"""
security/passwords.py
------------------------
Website login password hashing - PBKDF2-HMAC-SHA256 via hashlib
(stdlib, no bcrypt/passlib dependency required). 200,000 iterations
is in line with current OWASP guidance for PBKDF2-SHA256.

Separate from security/encryption.py, which handles MT5 passwords
(reversible, because the app needs the real password back to log
into MT5). Website passwords here are one-way only.
"""

import hashlib
import hmac
import os

_ITERATIONS = 200_000
_ALGO = "sha256"


def hash_password(plaintext: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac(_ALGO, plaintext.encode(), salt, _ITERATIONS)
    return f"pbkdf2_{_ALGO}${_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(plaintext: str, stored: str) -> bool:
    try:
        algo_tag, iterations, salt_hex, hash_hex = stored.split("$")
        algo = algo_tag.split("_", 1)[1]
        iterations = int(iterations)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except (ValueError, IndexError):
        return False
    dk = hashlib.pbkdf2_hmac(algo, plaintext.encode(), salt, iterations)
    return hmac.compare_digest(dk, expected)
