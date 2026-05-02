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

CREATE TABLE IF NOT EXISTS signal_decisions (
  signal_id TEXT PRIMARY KEY,
  strategy_id TEXT NOT NULL,
  strategy_version TEXT NOT NULL,
  model_version TEXT,
  prompt_version TEXT,
  config_hash TEXT NOT NULL,
  code_commit_sha TEXT NOT NULL,
  market_id TEXT NOT NULL,
  condition_id TEXT,
  token_id TEXT,
  outcome TEXT NOT NULL,
  side TEXT NOT NULL,
  source_health_json TEXT NOT NULL,
  market_snapshot_json TEXT NOT NULL,
  model_probability_raw REAL,
  model_probability_adjusted REAL,
  confidence REAL,
  edge REAL,
  risk_decision TEXT NOT NULL,
  risk_reason TEXT,
  final_action TEXT NOT NULL,
  human_reason TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS trade_lifecycle (
  trade_id TEXT PRIMARY KEY,
  signal_id TEXT NOT NULL,
  mode TEXT NOT NULL,
  entry_time TEXT,
  entry_expected_price REAL,
  entry_fill_price REAL,
  entry_slippage REAL,
  exit_model TEXT,
  exit_time TEXT,
  exit_price REAL,
  exit_reason TEXT,
  gross_pnl REAL,
  net_pnl REAL,
  max_adverse_excursion REAL,
  max_favorable_excursion REAL,
  status TEXT NOT NULL,
  payload_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS agent_memories (
  memory_id TEXT PRIMARY KEY,
  memory_type TEXT NOT NULL,
  status TEXT NOT NULL,
  strategy_id TEXT,
  wallet TEXT,
  market_category TEXT,
  content_json TEXT NOT NULL,
  evidence_json TEXT NOT NULL,
  confidence REAL NOT NULL DEFAULT 0,
  active_in_paper INTEGER NOT NULL DEFAULT 0,
  active_in_live INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS hypotheses (
  hypothesis_id TEXT PRIMARY KEY,
  statement TEXT NOT NULL,
  status TEXT NOT NULL,
  evidence_json TEXT NOT NULL,
  proposed_test_json TEXT NOT NULL,
  result_json TEXT NOT NULL DEFAULT '{}',
  promoted_rule_id TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS strategy_experiments (
  run_id TEXT PRIMARY KEY,
  run_type TEXT NOT NULL,
  strategy_id TEXT NOT NULL,
  code_commit_sha TEXT NOT NULL,
  config_hash TEXT NOT NULL,
  data_quality TEXT NOT NULL,
  dataset_version TEXT,
  parameters_json TEXT NOT NULL,
  metrics_json TEXT NOT NULL,
  artifacts_json TEXT NOT NULL,
  started_at TEXT,
  ended_at TEXT
);

CREATE TABLE IF NOT EXISTS wallet_replay_runs (
  run_id TEXT PRIMARY KEY,
  wallet TEXT NOT NULL,
  mode TEXT NOT NULL,
  data_quality TEXT NOT NULL,
  delays_json TEXT NOT NULL,
  config_json TEXT NOT NULL,
  metrics_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS wallet_replay_trades (
  replay_trade_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  wallet TEXT NOT NULL,
  condition_id TEXT NOT NULL,
  asset_id TEXT NOT NULL,
  outcome TEXT NOT NULL,
  delay_seconds INTEGER NOT NULL,
  entry_time INTEGER,
  entry_price REAL,
  leader_entry_price REAL,
  exit_time INTEGER,
  exit_price REAL,
  exit_model TEXT NOT NULL,
  status TEXT NOT NULL,
  pnl REAL,
  roi REAL,
  worse_entry_cents REAL,
  skipped_reason TEXT,
  category TEXT,
  payload_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS wallet_scores (
  wallet TEXT PRIMARY KEY,
  score REAL NOT NULL,
  components_json TEXT NOT NULL,
  sample_size INTEGER NOT NULL,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS market_categories (
  condition_id TEXT PRIMARY KEY,
  slug TEXT,
  category TEXT NOT NULL,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""
