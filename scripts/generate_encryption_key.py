"""Run once: python scripts/generate_encryption_key.py
Copy the printed value into .env as ENCRYPTION_KEY=<value>.
Back it up somewhere safe - losing it makes every stored MT5 password
unrecoverable."""

from cryptography.fernet import Fernet

if __name__ == "__main__":
    print(Fernet.generate_key().decode())
