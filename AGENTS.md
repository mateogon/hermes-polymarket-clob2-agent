# AGENTS.md - Hermes Polymarket CLOB V2 Agent

## Project Purpose

This repo is a safe, paper-first research system for Polymarket CLOB V2.

It supports:

- public-data market discovery
- CLOB public dry-run
- wallet-flow research
- historical-approx wallet replay
- learning loop / experiment tracking
- paper-only candidate rules
- future local L2 replay and paper strategy arena

It must not place live orders.

## Non-Negotiable Safety Rules

- Never enable live trading.
- Never ask for private keys.
- Never print, store, or commit secrets.
- Never modify `src/hermes_polymarket/execution/live_executor.py` to post orders.
- Never add proxy/IP-rotation, Cloudflare bypass, or geo-bypass logic.
- Never increase risk caps without explicit human instruction.
- Never make candidate rules active in live mode.
- All wallet-flow, replay, learning, and strategy work is research/paper only.
- Live promotion is unsupported.

## Required Commands After Any Code Change

Run:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall src scripts tests
.venv/bin/python -m hermes_polymarket.cli live --market test-market --side YES --amount 5 --live
```

Expected live output:

```text
Refusing live trading: ALLOW_LIVE_TRADING is not true
```

## Development Workflow

1. Plan first.
2. Make small patches.
3. Add tests for every new behavior.
4. Keep replay outputs labeled by data quality:
   - `historical_approx`
   - `local_l2`
   - `paper_live`
5. Never interpret `historical_approx` replay as executable L2 truth.
6. Write generated run artifacts under `artifacts/runs/<run_id>/`.
7. Do not commit artifacts, local DBs, logs, or secrets.

## Data Quality Labels

```text
historical_approx:
  Data API trades and/or public price history. Not executable L2 truth.

local_l2:
  Locally recorded Polymarket orderbook snapshots and deltas.

paper_live:
  Forward paper execution from live public data.
```

## Current Priority Order

```text
plan_4_6_fetch_backfill_and_replay_quality
plan_5_crypto_latency_measurement
plan_6_local_l2_recorder_and_replay
plan_7_paper_strategy_arena
plan_8_pre_live_safety_audit
```

## Allowed Commands

```bash
.venv/bin/python -m hermes_polymarket.cli smoke
.venv/bin/python -m hermes_polymarket.cli dry-run --fixture --market fixture-market --side YES --amount 5
.venv/bin/python -m hermes_polymarket.cli dry-run --token-id TOKEN_ID --side YES --amount 5
.venv/bin/python -m hermes_polymarket.cli wallet-flow fetch --wallet coinman2 --limit 100
.venv/bin/python -m hermes_polymarket.cli wallet-flow replay --wallet coinman2 --delay 0,2,5,15,30,120,600 --mode historical-approx --exit-model leader_exit
.venv/bin/python -m hermes_polymarket.cli wallet-flow score --wallet coinman2
.venv/bin/python -m hermes_polymarket.cli wallet-flow leaderboard
.venv/bin/python -m hermes_polymarket.cli learning daily-report
.venv/bin/python -m hermes_polymarket.cli learning weekly-review
```

## Forbidden Commands / Actions

- Do not set `ALLOW_LIVE_TRADING=true`.
- Do not run live orders.
- Do not add real private keys to `.env`.
- Do not commit `.env`, `data/`, `logs/`, or `artifacts/`.
- Do not create code that signs or posts orders.
- Do not use residential proxies, IP rotation, or geobypass.
