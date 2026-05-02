# Minimal Architecture Proposal

Stage 1 conclusion: build a new project, not a fork. The cloned repos are references with incompatible assumptions around CLOB V2, live execution, fees, and safety.

## Design Principles

1. `paper` is the default and must work without secrets.
2. `dry-run` builds and validates intended orders without signing or posting.
3. `live` is disabled unless all explicit gates pass.
4. Pricing decisions use executable CLOB orderbooks, not Gamma `outcomePrices`.
5. Signals produce proposals; risk/execution layers decide whether anything can happen.
6. All private-key and API credential handling stays in `.env` and is redacted from logs.

## Proposed Source Layout

```text
src/hermes_polymarket/
  cli.py
  config.py
  logging_utils.py

  polymarket/
    clob_v2_client.py
    gamma_client.py
    market_data.py
    orderbook.py
    types.py

  execution/
    paper_engine.py
    dry_run_executor.py
    live_executor.py
    order_validator.py

  signals/
    base.py
    weather_signal.py
    btc_microstructure_signal.py
    news_signal.py
    llm_signal.py

  risk/
    kelly.py
    risk_manager.py
    exposure.py
    circuit_breakers.py

  storage/
    db.py
    models.py
    journal.py

  backtest/
    runner.py
    metrics.py
```

## Module Responsibilities

### `polymarket/clob_v2_client.py`

Use `py-clob-client-v2` only. Provide public methods without secrets:

- health
- markets/market metadata
- `getClobMarketInfo(conditionID)` or equivalent
- orderbook
- midpoint/spread if available

Private client initialization is lazy and only allowed when `.env` has the required variables. It must not manually add V1 order fields.

### `polymarket/market_data.py`

Resolve Gamma market/event data to actual CLOB condition IDs and token IDs. Gamma can be used for discovery, titles, tags, and metadata. Gamma prices are reference-only and must not be used as executable bid/ask.

### `polymarket/orderbook.py`

Adapt the `agent-next` paper simulator:

- buy walks asks from lowest price upward
- sell walks bids from highest price downward
- FOK rejects incomplete fills
- FAK allows partial fills
- returns average fill price, shares, cost/proceeds, fees placeholder, slippage, liquidity status, fills by level

### `risk/kelly.py`

Implement Quarter-Kelly using executable price:

```text
b = (1 - entry_price) / entry_price
q = 1 - win_prob
full_kelly = (b * win_prob - q) / b
quarter_kelly = 0.25 * max(0, full_kelly)
```

Probability adjustment:

```text
p_adjusted = market_price + confidence_discount * (model_probability - market_price)
```

Defaults:

- confidence discount <= 0.50
- clip probability to `[0.05, 0.95]`
- reject edge > 0.30 unless manually approved
- reject entry `< 0.03` or `> 0.97`

### `risk/risk_manager.py`

Centralize all gates:

- max order USD
- max per-market exposure
- max open positions
- daily loss limit
- max portfolio exposure percent
- min edge
- min liquidity
- max slippage
- min hours to expiry
- stale orderbook rejection
- live trading gates

### `execution/paper_engine.py`

Simulate fills against real CLOB orderbooks, persist to SQLite, and update:

- cash
- open positions
- realized P&L
- unrealized P&L
- per-market exposure
- daily P&L
- signal reason/journal record

### `execution/dry_run_executor.py`

Build the exact proposed order and validate everything except signing/posting. Output should include:

- market
- token ID
- side
- amount
- executable price source
- estimated fill/slippage/liquidity
- risk decision
- reason for reject or allow

### `execution/live_executor.py`

Keep empty or stubbed until paper and dry-run pass. When implemented:

- requires `ALLOW_LIVE_TRADING=true`
- requires explicit `--live`
- uses `py-clob-client-v2`
- uses limit/FOK/FAK only
- checks V2 min tick, min order size, token IDs, and fee metadata
- fails closed on SDK, access, jurisdiction, Cloudflare, balance, or ambiguity errors
- never retries with proxy/IP rotation

## Minimal Build Order

1. Project metadata, config, `.env.example`, and CLI skeleton.
2. Public CLOB V2 smoke script.
3. Orderbook simulator and tests.
4. Quarter-Kelly and risk manager tests.
5. Paper engine and SQLite journal.
6. Dry-run executor.
7. Conservative signal modules.
8. Live executor only after the above pass.

## Initial Quality Gates

- `rg "py_clob_client|py-clob-client" src tests scripts` must not show legacy SDK usage.
- `rg "feeRateBps|nonce|taker" src tests scripts` must not show live order creation usage.
- `pytest` passes.
- Public-data smoke works without `.env`.
- Paper scan works without `.env`.
- Dry-run refuses unsafe or ambiguous orders.
- Live command refuses unless `ALLOW_LIVE_TRADING=true` and `--live` are both present.

## Next Implementation Target

Implement Phase 2 and Phase 3 together:

1. `pyproject.toml`, `.env.example`, config files, package skeleton.
2. Public CLOB V2 client with no-secret smoke.
3. Orderbook fill simulator copied conceptually from `agent-next`, rewritten under local types.
4. Tests for FOK/FAK, multi-level fills, empty book rejection, slippage, and cost/share math.
