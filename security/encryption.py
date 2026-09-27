"""
security/encryption.py
-------------------------
MT5 passwords encrypted at rest with Fernet (symmetric, authenticated).
Key comes only from ENCRYPTION_KEY env var - never stored in the DB,
never hard-coded. Generate one with scripts/generate_encryption_key.py.

Never log or return a decrypted value except at the moment of an MT5
login call.
"""

from cryptography.fernet import Fernet, InvalidToken

from config import settings


class DecryptionError(Exception):
    pass


def _fernet() -> Fernet:
    if not settings.ENCRYPTION_KEY:
        raise RuntimeError(
            "ENCRYPTION_KEY is not set. Run scripts/generate_encryption_key.py "
            "and add the value to .env before storing any MT5 account."
        )
    return Fernet(settings.ENCRYPTION_KEY.encode())


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise DecryptionError("Wrong ENCRYPTION_KEY or corrupted data.") from exc
