# Hermes Polymarket CLOB V2 Agent

Local project workspace for a safe Polymarket CLOB V2 trading agent.

Current stage: safe paper-first scaffold plus public-data intelligence layer, learning loop, and historical-approx wallet replay.

Created artifacts:

- `docs/stage_1_prompt.md` - saved project prompt and constraints
- `repo_audit.md` - cloned repo audit and reuse decisions
- `design.md` - minimal architecture proposal
- `external_repos/` - cloned reference repos

Live trading is not implemented and must remain disabled until paper mode, dry-run, tests, CLOB V2 validation, and explicit live gates are complete.

## Setup

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
```

Copy `.env.example` to `.env` only for local config. Do not paste private keys into chat or commit `.env`.

## Safe Commands

Run tests:

```bash
.venv/bin/python -m pytest -q
```

Public CLOB/Gamma smoke:

```bash
.venv/bin/python -m hermes_polymarket.cli smoke
```

Fixture dry-run, no network:

```bash
.venv/bin/python -m hermes_polymarket.cli dry-run --market fixture-market --side YES --amount 5 --fixture
```

Real public-data dry-run by CLOB token ID:

```bash
.venv/bin/python -m hermes_polymarket.cli dry-run --token-id TOKEN_ID --side YES --amount 5
```

Wallet-flow metrics report:

```bash
.venv/bin/python -m hermes_polymarket.cli wallet-flow report
```

Wallet replay commands:

```bash
.venv/bin/python -m hermes_polymarket.cli wallet-flow fetch --wallet coinman2 --limit 100
.venv/bin/python -m hermes_polymarket.cli wallet-flow replay --wallet coinman2 --delay 0,2,5,15,30,120,600 --mode historical-approx --exit-model leader_exit
.venv/bin/python -m hermes_polymarket.cli wallet-flow score --wallet coinman2
.venv/bin/python -m hermes_polymarket.cli wallet-flow leaderboard
.venv/bin/python -m hermes_polymarket.cli wallet-flow exit-coverage --wallet coinman2
.venv/bin/python -m hermes_polymarket.cli wallet-flow positions fetch --wallet coinman2 --kind current
.venv/bin/python -m hermes_polymarket.cli wallet-flow positions fetch --wallet coinman2 --kind closed --page-size 50 --max-pages 20
.venv/bin/python -m hermes_polymarket.cli wallet-flow positions report --wallet coinman2
```

Replay now reads persisted wallet trades from SQLite. Run `wallet-flow fetch` first; replay refuses clearly if there are no stored trades for that wallet. Output is labeled `historical_approx` unless backed by locally recorded L2 snapshots. In this mode, entry prices are approximated from public wallet trades, not executable L2 orderbooks, so slippage is not reliable yet.

Backfill and quality-export variants:

```bash
.venv/bin/python -m hermes_polymarket.cli wallet-flow fetch --wallet coinman2 --page-size 100 --max-pages 10 --limit-total 1000
.venv/bin/python -m hermes_polymarket.cli wallet-flow replay --wallet coinman2 --delay 0,2,5,15,30,120,600 --mode historical-approx --exit-model leader_exit --amount 5 --export-csv --quality-warnings
```

Each replay also writes:

- `wallet_replay_runs` and `wallet_replay_trades`
- a `strategy_experiments` row
- inactive candidate memories when enough evidence exists
- artifacts under `artifacts/runs/<run_id>/`, including `manifest.json`; with `--export-csv`, replay also writes CSVs for trades, delay metrics, skipped reasons, and PnL by category

`resolution_exit` and `risk_exit` are intentionally honest placeholders in historical-approx mode: they return pending reasons until resolution data or local price paths are available.

If `leader_exit` replay produces zero closed trades, run `wallet-flow exit-coverage`. It reports whether observed buys have matching sells for the same wallet, condition ID, and asset ID before moving on to local L2 or crypto latency work.

Use `wallet-flow positions` to inspect public current and closed Data API positions. This is useful when a wallet appears to hold to resolution, redeem, or hedge with opposite assets instead of selling the same asset.

Crypto latency measurement commands are measurement/paper-only:

```bash
.venv/bin/python -m hermes_polymarket.cli crypto-latency discover
.venv/bin/python -m hermes_polymarket.cli crypto-latency record --seconds 300
.venv/bin/python -m hermes_polymarket.cli crypto-latency report
.venv/bin/python -m hermes_polymarket.cli crypto-latency opportunities
```

The first version stores consensus ticks, latency events, market windows, and paper opportunities. `record` is intentionally a safe skeleton until local L2 recorder orchestration is added.

Live gate check, expected to refuse by default:

```bash
.venv/bin/python -m hermes_polymarket.cli live --market MARKET_ID --side YES --amount 5 --live
```

## Data Layer

The data-source layer normalizes public events into `DataEvent` records before they reach signals:

- Polymarket CLOB REST/Gamma for market resolution and dry-run orderbooks.
- Polymarket market WebSocket normalizer for book, price change, last trade, best bid/ask, and resolution events.
- Polymarket Data API `/trades` for public wallet-flow observation.
- Polymarket RTDS, Binance, Coinbase, and Kraken normalizers for crypto price context.

Signals remain signal-only. Wallet flow can produce paper-copy candidates, but it cannot place live orders.

Wallet-flow reporting is entry-copyability only until an exit model exists. The report intentionally marks PnL as `not_computed_no_exit_model`; paper PnL should only be interpreted after a leader-exit, TP/SL/timeout, or resolution-payout model is implemented.

## Learning Loop

The agent learns through an auditable research loop, not by self-training or changing live code:

```text
observe -> journal -> evaluate -> reflect -> hypothesize -> replay -> paper -> promote/reject
```

Learning records store code commit, config hash, market snapshots, source health, risk decision, final action, and human-readable rationale. Reflections and memories can create candidate rules, but promotion is paper-only and requires explicit human approval.

Learning commands:

```bash
.venv/bin/python -m hermes_polymarket.cli learning daily-report
.venv/bin/python -m hermes_polymarket.cli learning weekly-review
.venv/bin/python -m hermes_polymarket.cli learning hypotheses
.venv/bin/python -m hermes_polymarket.cli learning memories search --query coinman2
.venv/bin/python -m hermes_polymarket.cli learning promote-candidate --rule-id RULE_ID --paper-only --human-approved
.venv/bin/python -m hermes_polymarket.cli learning retire-rule --rule-id RULE_ID
```

Learning modules cannot activate live rules, modify live execution, or raise live risk caps. Live promotion is intentionally unsupported.

## Reference Repos Cloned

- `external_repos/chainstacklabs-polyclaw`
- `external_repos/agent-next-polymarket-paper-trader`
- `external_repos/suislanchez-polymarket-kalshi-weather-bot`
- `external_repos/yangyuan-zhen-PolyWeather`
- `external_repos/arkyu2077-polyclaw`
- `external_repos/PolyScripts-polymarket-market-maker-bot`
- `external_repos/PolyScripts-polymarket-arbitrage-trading-bot-pack-5min-15min-kalshi`
- `external_repos/PolyScripts-polymarket-5min-15min-1hr-btc-arbitrage-trading-bot-rust`

## Current Decision

Build a clean new Python project. Do not fork any audited repo. Reuse paper-simulation and signal ideas only after rewriting them around CLOB V2, pUSD, safe defaults, and centralized risk gates.
