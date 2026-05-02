"""SQLite schema constants."""

SCHEMA = """
CREATE TABLE IF NOT EXISTS account (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  starting_balance REAL NOT NULL,
  cash REAL NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS trades (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  mode TEXT NOT NULL,
  market_id TEXT NOT NULL,
  condition_id TEXT NOT NULL,
  token_id TEXT NOT NULL,
  outcome TEXT NOT NULL,
  side TEXT NOT NULL,
  avg_price REAL NOT NULL,
  shares REAL NOT NULL,
  amount_usd REAL NOT NULL,
  fee REAL NOT NULL,
  slippage REAL NOT NULL,
  signal_reason TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS positions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  market_id TEXT NOT NULL,
  condition_id TEXT NOT NULL,
  token_id TEXT NOT NULL,
  outcome TEXT NOT NULL,
  shares REAL NOT NULL,
  avg_entry_price REAL NOT NULL,
  total_cost REAL NOT NULL,
  realized_pnl REAL NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'open',
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(condition_id, token_id, outcome, status)
);

CREATE TABLE IF NOT EXISTS journal (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_type TEXT NOT NULL,
  message TEXT NOT NULL,
  payload_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS data_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT NOT NULL,
  event_type TEXT NOT NULL,
  event_ts_ms INTEGER,
  received_ts_ms INTEGER NOT NULL,
  latency_ms INTEGER,
  event_key TEXT NOT NULL,
  payload_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_data_events_source_type
ON data_events(source, event_type, received_ts_ms);

CREATE INDEX IF NOT EXISTS idx_data_events_key
ON data_events(event_key, received_ts_ms);

CREATE TABLE IF NOT EXISTS source_health (
  source TEXT PRIMARY KEY,
  last_seen_ts_ms INTEGER NOT NULL,
  last_latency_ms INTEGER,
  messages_seen INTEGER NOT NULL DEFAULT 0,
  errors_seen INTEGER NOT NULL DEFAULT 0,
  dropped_events INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'unknown',
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""
