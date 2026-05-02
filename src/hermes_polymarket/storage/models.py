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

CREATE TABLE IF NOT EXISTS raw_source_samples (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT NOT NULL,
  event_type TEXT NOT NULL,
  event_key TEXT NOT NULL,
  received_ts_ms INTEGER NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_raw_source_samples_source
ON raw_source_samples(source, received_ts_ms);

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

CREATE TABLE IF NOT EXISTS wallet_observed_trades (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  wallet TEXT NOT NULL,
  condition_id TEXT NOT NULL,
  asset_id TEXT NOT NULL,
  outcome TEXT NOT NULL,
  side TEXT NOT NULL,
  price REAL NOT NULL,
  size REAL NOT NULL,
  timestamp INTEGER NOT NULL,
  slug TEXT,
  title TEXT,
  tx_hash TEXT,
  raw_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(wallet, tx_hash, condition_id, asset_id, side, timestamp)
);

CREATE TABLE IF NOT EXISTS wallet_current_positions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  wallet TEXT NOT NULL,
  condition_id TEXT NOT NULL,
  asset_id TEXT NOT NULL,
  outcome TEXT NOT NULL,
  size REAL NOT NULL,
  avg_price REAL NOT NULL,
  initial_value REAL NOT NULL,
  current_value REAL NOT NULL,
  cash_pnl REAL NOT NULL,
  percent_pnl REAL NOT NULL,
  total_bought REAL NOT NULL,
  realized_pnl REAL NOT NULL,
  cur_price REAL NOT NULL,
  redeemable INTEGER NOT NULL DEFAULT 0,
  mergeable INTEGER NOT NULL DEFAULT 0,
  negative_risk INTEGER NOT NULL DEFAULT 0,
  opposite_asset TEXT,
  opposite_outcome TEXT,
  slug TEXT,
  title TEXT,
  event_slug TEXT,
  end_date TEXT,
  raw_json TEXT NOT NULL DEFAULT '{}',
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(wallet, condition_id, asset_id)
);

CREATE TABLE IF NOT EXISTS wallet_closed_positions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  wallet TEXT NOT NULL,
  condition_id TEXT NOT NULL,
  asset_id TEXT NOT NULL,
  outcome TEXT NOT NULL,
  avg_price REAL NOT NULL,
  total_bought REAL NOT NULL,
  realized_pnl REAL NOT NULL,
  cur_price REAL NOT NULL,
  timestamp INTEGER NOT NULL,
  opposite_asset TEXT,
  opposite_outcome TEXT,
  slug TEXT,
  title TEXT,
  event_slug TEXT,
  end_date TEXT,
  raw_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(wallet, condition_id, asset_id, timestamp)
);

CREATE TABLE IF NOT EXISTS wallet_scores (
  wallet TEXT PRIMARY KEY,
  score REAL NOT NULL,
  warnings_json TEXT NOT NULL DEFAULT '[]',
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

CREATE TABLE IF NOT EXISTS crypto_market_windows (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  condition_id TEXT NOT NULL,
  slug TEXT NOT NULL,
  question TEXT,
  symbol TEXT NOT NULL,
  yes_token_id TEXT NOT NULL,
  no_token_id TEXT NOT NULL,
  window_start_ts INTEGER,
  window_end_ts INTEGER,
  reference_price REAL,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(condition_id, yes_token_id, no_token_id)
);

CREATE TABLE IF NOT EXISTS crypto_market_watchlist (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  condition_id TEXT NOT NULL,
  slug TEXT NOT NULL,
  question TEXT,
  symbol TEXT NOT NULL,
  yes_token_id TEXT NOT NULL,
  no_token_id TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1,
  discovered_at_ms INTEGER NOT NULL,
  end_ts_ms INTEGER,
  raw_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(condition_id, yes_token_id, no_token_id)
);

CREATE TABLE IF NOT EXISTS crypto_consensus_ticks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  symbol TEXT NOT NULL,
  consensus_price REAL NOT NULL,
  sources_json TEXT NOT NULL,
  max_deviation_pct REAL NOT NULL,
  received_ts_ms INTEGER NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_crypto_consensus_symbol_ts
ON crypto_consensus_ticks(symbol, received_ts_ms);

CREATE TABLE IF NOT EXISTS crypto_latency_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id TEXT NOT NULL UNIQUE,
  symbol TEXT NOT NULL,
  condition_id TEXT,
  external_move_pct REAL NOT NULL,
  external_move_detected_ts_ms INTEGER NOT NULL,
  polymarket_reprice_ts_ms INTEGER,
  repricing_lag_ms INTEGER,
  spread_before REAL,
  depth_before_usd REAL,
  stale_quote_depth_usd REAL,
  source_health_json TEXT NOT NULL DEFAULT '{}',
  payload_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS crypto_latency_opportunities (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  opportunity_id TEXT NOT NULL UNIQUE,
  event_id TEXT NOT NULL,
  token_id TEXT NOT NULL,
  outcome TEXT NOT NULL,
  side TEXT NOT NULL,
  amount_usd REAL NOT NULL,
  avg_price REAL,
  shares REAL,
  fill_status TEXT NOT NULL,
  risk_allowed INTEGER NOT NULL,
  risk_reason TEXT,
  data_quality TEXT NOT NULL DEFAULT 'paper_live',
  payload_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS l2_book_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  token_id TEXT NOT NULL,
  event_ts_ms INTEGER,
  received_ts_ms INTEGER NOT NULL,
  bids_json TEXT NOT NULL,
  asks_json TEXT NOT NULL,
  raw_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_l2_book_snapshots_token_ts
ON l2_book_snapshots(token_id, received_ts_ms);

CREATE TABLE IF NOT EXISTS l2_price_changes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  token_id TEXT NOT NULL,
  market TEXT,
  side TEXT NOT NULL,
  price REAL NOT NULL,
  size REAL NOT NULL,
  removed INTEGER NOT NULL DEFAULT 0,
  event_ts_ms INTEGER,
  received_ts_ms INTEGER NOT NULL,
  raw_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_l2_price_changes_token_ts
ON l2_price_changes(token_id, received_ts_ms);

CREATE TABLE IF NOT EXISTS l2_bbo_updates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  token_id TEXT NOT NULL,
  best_bid REAL,
  best_ask REAL,
  spread REAL,
  event_ts_ms INTEGER,
  received_ts_ms INTEGER NOT NULL,
  raw_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_l2_bbo_updates_token_ts
ON l2_bbo_updates(token_id, received_ts_ms);

CREATE TABLE IF NOT EXISTS l2_recorder_runs (
  run_id TEXT PRIMARY KEY,
  token_ids_json TEXT NOT NULL,
  seconds INTEGER NOT NULL,
  events_seen INTEGER NOT NULL DEFAULT 0,
  snapshots_seen INTEGER NOT NULL DEFAULT 0,
  deltas_seen INTEGER NOT NULL DEFAULT 0,
  bbo_seen INTEGER NOT NULL DEFAULT 0,
  started_at TEXT NOT NULL,
  ended_at TEXT,
  status TEXT NOT NULL
);
"""
