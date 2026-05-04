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

## Long-Running Paper/Research Jobs

When launching long-running paper or research jobs, do not rely on a fragile
interactive shell wrapper. Jobs that are expected to outlive the current command
turn must follow this checklist:

1. Use `nohup` or another detached runner.
2. Use absolute paths for the Python binary, log files, DB paths, artifact paths,
   and working directory-sensitive inputs.
3. Pass per-run DB paths with `HERMES_DATABASE_PATH=/absolute/path/to/run.sqlite3`.
4. Redirect stdout/stderr to a concrete log file before backgrounding.
5. Write a manifest next to the logs with:
   - command purpose
   - started_at
   - expected_end_at
   - PIDs
   - log paths
   - DB paths
   - exact command or enough args to reconstruct it
6. After 2-5 seconds, verify:
   - PIDs are still running with `ps -p ...`
   - log files exist
   - DB/artifact files exist if the command should create them early
7. If a process exits immediately, inspect the log and report that as a failed
   launch. Do not count it as a completed experiment.
8. For runs longer than a few minutes, create a thread reminder/heartbeat for
   the expected end time and include the manifest/log paths in the reminder.
9. Never run `watch-v2`, multi-strike paper, or campaign batches without
   preserving enough logs and manifest data to audit whether the run actually
   started.

Minimal pattern:

```bash
ROOT="$PWD/logs/<campaign>/<timestamp>"
DATAROOT="$PWD/data/<campaign>/<timestamp>"
mkdir -p "$ROOT" "$DATAROOT"

nohup env HERMES_DATABASE_PATH="$DATAROOT/run.sqlite3" \
  "$PWD/.venv/bin/python" -m hermes_polymarket.cli ... \
  > "$ROOT/run.log" 2>&1 &
PID=$!

printf '{"pid":%s,"log":"%s","db":"%s"}\n' \
  "$PID" "$ROOT/run.log" "$DATAROOT/run.sqlite3" \
  > "$ROOT/manifest.json"

sleep 2
ps -p "$PID"
test -f "$ROOT/run.log"
```

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
