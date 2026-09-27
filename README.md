# CopyTrade Pro SaaS

A Telegram → MT5 copy-trading SaaS. Customers register, pay manually
(Telebirr/CBE), get their access approved by an admin, connect their
own MT5 account, and have Ab Marshall's Telegram signals copied into
their account according to their own risk settings.

## Framework choice - please read before judging the code style

This codebase is built on **Python's standard library** (`http.server`
via `wsgiref`, `sqlite3`, `hashlib`, `unittest`) plus two small,
dependency-light libraries (`cryptography`, `itsdangerous`). That is a
deliberate choice, not an oversight: it was built and verified inside
a sandbox with **no internet access**, so anything requiring
`pip install` (FastAPI, SQLAlchemy, Postgres drivers, Telethon) could
never actually be run or tested there. Rather than hand you framework
code with confident-sounding claims that were never executed, every
flow that *can* run without network access - auth, payments, risk,
the signal engine, customer isolation, admin authorization - was
built so it actually runs, and actually was run, in that sandbox. See
**"What has and hasn't been verified"** below for the precise line.

The architecture keeps business logic (`app/auth.py`,
`app/customer.py`, `app/admin.py`, `core/*`, `workers/*`) completely
separate from the HTTP layer (`app/http_app.py`). If you want to move
to FastAPI + SQLAlchemy + Postgres for real production scale, that's
a rewrite of `app/http_app.py` and `database/db.py` only - nothing
else needs to change, and the same tests in `tests/` still describe
the behavior you need to preserve.

## Requirements

- Python 3.10+
- No external services required for local development (SQLite, in
  the `storage/` folder created automatically)
- For production: PostgreSQL (schema is in `database/schema.sql`,
  written to be portable, but the current `database/db.py` speaks
  `sqlite3` directly - swapping in `psycopg2` there is what actually
  makes Postgres usable, and that step is untested)

## Setup

```powershell
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and fill in real values:

```powershell
copy .env.example .env
python scripts\generate_encryption_key.py
```

Paste the printed key into `.env` as `ENCRYPTION_KEY=...`. Generate a
`SESSION_SECRET` the same way (any long random string works, e.g.
`python -c "import secrets; print(secrets.token_hex(32))"`).

Leave `DRY_RUN=true` while testing - this guarantees no real MT5 order
is ever sent, even once real MT5 credentials are configured.

## Create your first admin account

```powershell
python scripts\create_admin.py owner@yourcompany.com SomeStrongPassword123
```

## Run

```powershell
python main.py
```

This starts the web/API server (default `http://127.0.0.1:8000`) and,
if `TELEGRAM_API_ID`/`TELEGRAM_API_HASH` are configured, the Telegram
listener in a background thread. If they're not configured, the
listener logs a warning and stays off - the rest of the app is
unaffected.

## API (customer)

| Route | Method | Purpose |
|---|---|---|
| `/auth/register` | POST | `{email, password}` |
| `/auth/login` | POST | `{email, password}` |
| `/auth/me` | GET | current session |
| `/auth/logout` | POST | |
| `/customer/status` | GET | access/settings/MT5 summary |
| `/customer/mt5` | POST | `{login, password, server}` |
| `/customer/mt5/test` | POST | test the MT5 connection |
| `/customer/settings` | POST | `{fixed_lot, max_open_trades, max_daily_loss, max_drawdown_percent}` |
| `/customer/copy-toggle` | POST | `{enabled}` |
| `/customer/payments` | POST/GET | submit a receipt (base64) / list your own |
| `/customer/orders` | GET | your own order history |

## API (admin - requires an admin account)

| Route | Method | Purpose |
|---|---|---|
| `/admin/customers` | GET | list all customers |
| `/admin/customers/{id}/active` | POST | `{active}` enable/disable |
| `/admin/customers/{id}/activate` | POST | `{days}` manual access grant |
| `/admin/payments/pending` | GET | queue to review |
| `/admin/payments/{id}/approve` | POST | activates access |
| `/admin/payments/{id}/reject` | POST | `{reason}` |
| `/admin/trading/overview` | GET | open trades / active customers |
| `/admin/emergency-stop` | POST | `{active}` global copy kill-switch |
| `/admin/system/health` | GET | recent system events |

Every route above went through a real HTTP request in this
project's verification (see below) - not just a design on paper.

## Testing

```powershell
python -m unittest discover -s tests -v
```

42 tests, covering: password hashing, MT5 credential encryption,
session tokens, the Ab Marshall parser (real message formats, and the
"this looks like a signal but isn't" cases), the risk engine
(especially the nullable-limit rule - a `NULL` daily-loss limit must
never behave like a limit of zero), full register/login/logout,
customer data isolation (Customer A cannot see or affect Customer B's
MT5 account, payment receipts, or risk settings), admin payment
approval/rejection and the resulting access state, the full signal
engine (parse-once, concurrent fan-out, duplicate-window protection,
one customer's MT5 failure never affecting another's), and a full
HTTP round-trip against a real running server (cookies, 401/403
enforcement, the complete customer journey).

## What has and hasn't been verified

**Actually run and verified, in this project's own sandbox:**
- The full test suite above (42/42, stable across repeated runs)
- A live server (`python main.py`) driven with real `curl` requests
  through the complete flow: register → add MT5 → test connection →
  submit payment receipt → admin approves → access becomes active →
  enable copying → admin sees the customer → customer blocked from
  admin routes (403)
- A real signal fed into the running engine (`GOLD sell now / SL
  4554 / TP 4400`), correctly parsed once, risk-checked, and filled
  by the (simulated) MT5 executor
- The MT5 auto-reconnect path: a worker's connection was forced into
  a disconnected state, then the next incoming signal correctly
  triggered a reconnect (using the stored encrypted credentials)
  before the risk check, and the order filled

**Built, but NOT executable in this sandbox (no network, no Windows,
no real credentials) - verify these yourself before trusting them:**
- `workers/mt5_executor.py`'s `RealMT5Executor` - the actual
  `MetaTrader5` Python package only installs on Windows. `DRY_RUN` in
  `.env` controls whether this class is even used; keep it `true`
  until you've tested `RealMT5Executor` directly against a demo MT5
  account.
- `integrations/telegram_listener.py` - `telethon` was never
  installed or run here. The message-filtering and single-parse
  logic reuses your old bot's proven pattern, but the actual
  Telegram connection has not been exercised.
- Anything Postgres-specific - only SQLite has been run.

## Known gaps for a first public launch

- **P/L tracking is not implemented.** `orders` records fills;
  nothing currently tracks when a position closes or its P/L, so
  `max_daily_loss` and `max_drawdown_percent` are enforced in the
  risk engine but always see `0` for "loss so far" until this is
  built. Don't advertise those limits as active to customers yet.
- **Receipt upload is base64-JSON**, not multipart file upload - fine
  for a fast MVP, worth revisiting for large files.
- **MT5 worker isolation is thread-based, not process-based** (see
  the comment in `workers/worker_manager.py`) - simpler to run and
  test, but if MetaTrader5's Python API turns out to need one OS
  process per account in practice on your machine, that's a contained
  change in one file.
- Telegram bot commands (`/status`, `/pause`, etc. from the product
  spec) are not implemented - only the passive listener is.
