"""
config/settings.py
---------------------
Single configuration source for the whole app. Nothing else in the
codebase reads os.environ directly - everything imports from here.
"""

import os
import secrets

_TRUE = ("1", "true", "yes", "on")


def _bool(name: str, default: str = "true") -> bool:
    return os.getenv(name, default).strip().lower() in _TRUE


def _load_dotenv():
    """Minimal .env loader (avoids a python-dotenv hard dependency for this MVP)."""
    path = os.path.join(BASE_DIR, ".env")
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_load_dotenv()

ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
IS_PRODUCTION = ENVIRONMENT == "production"

STORAGE_DIR = os.path.join(BASE_DIR, "storage")
RECEIPTS_DIR = os.path.join(STORAGE_DIR, "receipts")
# An empty DATABASE_PATH (e.g. "DATABASE_PATH=" in .env) must NOT override the
# default location - os.getenv's `default` argument only kicks in when the
# variable is unset, not when it's set-but-empty. `or` fixes that.
DB_PATH = os.getenv("DATABASE_PATH") or os.path.join(STORAGE_DIR, "copytrade.db")
# Postgres target for production is documented in README/requirements.txt.
# This MVP's database/db.py speaks plain SQL against sqlite3 directly;
# the schema (database/schema.sql) avoids sqlite-only syntax so it also
# runs on Postgres largely unchanged when that migration happens.
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DB_PATH}")

# Secrets - no insecure defaults allowed in production.
if IS_PRODUCTION:
    ENCRYPTION_KEY = os.environ["ENCRYPTION_KEY"]
    SESSION_SECRET = os.environ["SESSION_SECRET"]
else:
    ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY", "")
    SESSION_SECRET = os.getenv("SESSION_SECRET", "dev-only-" + secrets.token_hex(8))

SESSION_TTL_HOURS = int(os.getenv("SESSION_TTL_HOURS", "12"))

# --- Telegram (Ab Marshall only, per product spec) ---
TELEGRAM_API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH", "")
TELEGRAM_SESSION = os.getenv("TELEGRAM_SESSION", "copytrade_session")
AB_MARSHALL_CHANNEL = os.getenv("AB_MARSHALL_CHANNEL", "marshallfx_free_channel")
ADMIN_TELEGRAM_USERNAME = os.getenv("ADMIN_TELEGRAM_USERNAME", "")

# --- MT5 ---
MT5_TERMINAL_PATH = os.getenv("MT5_PATH", r"C:\Program Files\MetaTrader 5\terminal64.exe")

# --- Safety ---
DRY_RUN = _bool("DRY_RUN", "true")
DUPLICATE_WINDOW_SECONDS = int(os.getenv("DUPLICATE_WINDOW_SECONDS", "30"))

# --- Access / challenge ---
CHALLENGE_DURATION_DAYS = int(os.getenv("CHALLENGE_DURATION_DAYS", "30"))

# --- Web server ---
HTTP_HOST = os.getenv("HTTP_HOST", "127.0.0.1")
HTTP_PORT = int(os.getenv("HTTP_PORT", "8000"))

# --- CORS ---
# The frontend (Vite/TanStack dev server) runs on a different origin/port
# than this API, so the browser enforces CORS. Credentialed requests (the
# HttpOnly session_token cookie) require an exact origin - "*" is rejected
# by browsers whenever credentials are involved, so this must be a literal
# scheme+host+port. Comma-separate multiple origins if needed.
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:8080").split(",") if o.strip()]

# --- Payment methods shown to customers (admin-configurable text) ---
PAYMENT_INSTRUCTIONS = {
    "telebirr": os.getenv("PAY_TELEBIRR_INSTRUCTIONS", "Send to Telebirr number: (configure in .env)"),
    "cbe": os.getenv("PAY_CBE_INSTRUCTIONS", "Send to CBE account: (configure in .env)"),
}
CHALLENGE_PRICE = os.getenv("CHALLENGE_PRICE", "(configure in .env)")
