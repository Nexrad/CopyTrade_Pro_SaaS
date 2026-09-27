-- database/schema.sql
-- One source of truth for the schema. Written in portable SQL (no
-- SQLite-only pragmas beyond AUTOINCREMENT) so the move to Postgres
-- later is a schema translation, not a redesign.

CREATE TABLE IF NOT EXISTS users (
    id              TEXT PRIMARY KEY,
    email           TEXT NOT NULL UNIQUE,
    password_hash   TEXT NOT NULL,
    role            TEXT NOT NULL DEFAULT 'customer',   -- 'customer' | 'admin'
    is_active       INTEGER NOT NULL DEFAULT 1,
    telegram_username TEXT,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS customer_settings (
    user_id             TEXT PRIMARY KEY REFERENCES users(id),
    copy_enabled        INTEGER NOT NULL DEFAULT 0,
    provider_enabled    INTEGER NOT NULL DEFAULT 1,     -- Ab Marshall on/off for this customer
    fixed_lot           REAL NOT NULL DEFAULT 0.01,
    max_open_trades     INTEGER NOT NULL DEFAULT 5,
    max_daily_loss      REAL,                            -- NULL = no limit (never treat as 0)
    max_drawdown_percent REAL,                            -- NULL = no limit
    updated_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mt5_accounts (
    id                  TEXT PRIMARY KEY,
    user_id             TEXT NOT NULL REFERENCES users(id),
    login               TEXT NOT NULL,
    password_encrypted  TEXT NOT NULL,
    server              TEXT NOT NULL,
    connected           INTEGER NOT NULL DEFAULT 0,
    last_checked_at     TEXT,
    last_error          TEXT,
    created_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS payments (
    id                  TEXT PRIMARY KEY,
    user_id             TEXT NOT NULL REFERENCES users(id),
    method              TEXT NOT NULL,          -- 'telebirr' | 'cbe' | ...
    claimed_amount      REAL,
    receipt_path        TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'pending_review',  -- pending_review|approved|rejected
    rejection_reason    TEXT,
    submitted_at        TEXT NOT NULL,
    reviewed_at         TEXT,
    reviewed_by         TEXT REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS access (
    id                  TEXT PRIMARY KEY,
    user_id             TEXT NOT NULL REFERENCES users(id),
    status              TEXT NOT NULL DEFAULT 'expired',  -- active|expired
    access_start        TEXT,
    access_end          TEXT,
    activated_by         TEXT REFERENCES users(id),
    payment_id          TEXT REFERENCES payments(id),
    created_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS signals (
    id                  TEXT PRIMARY KEY,
    provider            TEXT NOT NULL,
    raw_text            TEXT NOT NULL,
    direction           TEXT,
    symbol              TEXT,
    entry_min           REAL,
    entry_max           REAL,
    sl                  REAL,
    tp                  REAL,
    fingerprint         TEXT NOT NULL,
    received_at         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    id                  TEXT PRIMARY KEY,
    user_id             TEXT NOT NULL REFERENCES users(id),
    signal_id           TEXT NOT NULL REFERENCES signals(id),
    symbol              TEXT NOT NULL,
    direction            TEXT NOT NULL,
    lot                 REAL NOT NULL,
    status              TEXT NOT NULL DEFAULT 'pending',  -- pending|filled|rejected|error
    broker_ticket       TEXT,
    error_detail        TEXT,
    requested_at        TEXT NOT NULL,
    executed_at         TEXT
);

CREATE TABLE IF NOT EXISTS audit_events (
    id                  TEXT PRIMARY KEY,
    actor_user_id       TEXT REFERENCES users(id),
    action              TEXT NOT NULL,
    target_user_id      TEXT REFERENCES users(id),
    detail              TEXT,             -- JSON text, never secrets
    created_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS system_events (
    id                  TEXT PRIMARY KEY,
    component           TEXT NOT NULL,     -- 'telegram'|'mt5_worker'|'signal_engine'
    level               TEXT NOT NULL DEFAULT 'info',
    message             TEXT NOT NULL,
    created_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runtime_settings (
    key                 TEXT PRIMARY KEY,
    value               TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_signals_fingerprint ON signals(fingerprint);
CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id);
CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status);
