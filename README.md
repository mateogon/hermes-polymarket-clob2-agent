# Hermes Polymarket CLOB V2 Agent

Local project workspace for a safe Polymarket CLOB V2 trading agent.

Current stage: safe paper-first scaffold plus public-data intelligence layer.

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
