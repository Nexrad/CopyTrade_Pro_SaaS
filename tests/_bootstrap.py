"""
tests/_bootstrap.py
----------------------
Imported first by every test module (before any `config`/`app`/`core`
import) so config.settings picks up a throwaway test database and
real-format secrets instead of touching your real .env or dev.db.
"""

import os
import tempfile

from cryptography.fernet import Fernet

_TMP_DIR = tempfile.mkdtemp(prefix="copytrade_test_")

os.environ["ENVIRONMENT"] = "development"
os.environ["DATABASE_PATH"] = os.path.join(_TMP_DIR, "test.db")
os.environ["ENCRYPTION_KEY"] = Fernet.generate_key().decode()
os.environ["SESSION_SECRET"] = "test-session-secret"
os.environ["DRY_RUN"] = "true"
