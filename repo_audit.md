# Repo Audit - Stage 1

Date: 2026-05-01

Scope: cloned and inspected the primary repos plus optional warning examples under `external_repos/`. No private keys were requested, no orders were placed, and no live trading code was executed.

Current Polymarket baseline verified from official docs:

- CLOB V2 production cutover was scheduled for 2026-04-28.
- Python SDK target is `py-clob-client-v2`.
- Production host is `https://clob.polymarket.com`.
- Collateral is pUSD.
- Live order creation must not manually use `feeRateBps`, `nonce`, or `taker`.
- Fees are dynamic and set at match time; use V2 SDK/market metadata such as `getClobMarketInfo(conditionID)`.

Source: https://docs.polymarket.com/v2-migration

## Audit Matrix

| repo | purpose | good parts to reuse | bad parts to avoid | CLOB V2 compatible? | uses old `py-clob-client`? | treats Gamma `outcomePrices` as bid/ask? | has paper mode? | has tests? | security concerns | final decision |
|---|---|---|---|---|---|---|---|---|---|---|
| `chainstacklabs/polyclaw` | OpenClaw Polymarket skill with wallet, CLOB execution, split/sell flow, and hedge discovery | Uses `py-clob-client-v2==1.0.0`; pUSD-aware docs and contract constants; wallet balance/approval flow; basic CLOB wrapper shape | Proxy/Cloudflare retry behavior; direct live `buy` flow; old README snippet still imports `py_clob_client`; split/sell flow needs careful slippage and orphan-token handling | partial/yes for SDK, but execution safety needs rewrite | no in dependencies; README contains old import example | yes for display/market data in `gamma_client.py`, not enough for execution | no | no tests found | Private key env var; proxy retry/IP-rotation pattern; live commands can execute real trades | use as CLOB V2 reference only, not as production base |
| `agent-next/polymarket-paper-trader` | Paper trading simulator using real Polymarket public orderbooks | Best orderbook simulator: walks asks for buys, bids for sells, FOK/FAK, slippage, SQLite, CLI, strong tests | V1-style fee endpoint/`fee_rate_bps`; no CLOB V2 market metadata; no live executor; broad agent strategy runner should not become live trading path | partial for public REST/orderbooks, not V2 SDK | no | no for execution; parses `outcomePrices` only as market metadata | yes | yes, extensive | Low; no private keys/live execution | use as main paper-engine reference |
| `suislanchez/polymarket-kalshi-weather-bot` | BTC 5m and weather signal simulator/dashboard | BTC slug/window logic; RSI/momentum/VWAP/SMA/skew signal ideas; weather ensemble probability and city/date parsing; SQLAlchemy simulation state | Uses Gamma `outcomePrices` as trade price; no CLOB orderbook execution; no CLOB V2 SDK; LLM trade decision can default permissively in one path; no tests | no for CLOB execution | no dependency, but research doc references old `py-clob-client` | yes, as market price | yes, simulation mode | no tests found | Kalshi private key path support; LLM analysis should never directly trade | reference only for signal ideas |
| `yangyuan-zhen/PolyWeather` | Production weather intelligence and Polymarket read-only scanner | Strong settlement-oriented weather modeling; bucket mapping; explicit CLOB BUY=ask/SELL=bid semantics; quarter-Kelly reference; tests; model-vs-market separation | Large product stack; AGPL license; no production trading executor; proxy config exists for data collection; payment/onchain code irrelevant | partial for read-only public CLOB REST, not SDK live execution | no direct dependency | uses `outcomePrices` as fallback/reference, but prefers CLOB price/book when available | read-only, not trading paper engine | yes | AGPL license; many unrelated payment/auth surfaces; HTTP proxy settings should not be reused for trading | use only for weather intelligence and bucket mapping concepts |
| `arkyu2077/polyclaw` | News edge scanner, paper/live positions, risk filters, decision journal | News ingestion architecture; fuzzy matching; decision journal; signal filters; paper position tracking; useful tests; some conservative config defaults | Legacy `py_clob_client`; USDC.e terminology; old fee model; live order placement via V1 SDK; stores auto-derived CLOB creds in `.env`; uses Gamma prices for entry/position pricing | no | yes | yes, frequently as market price | yes | yes | Private key and CLOB creds in `.env`; old live executor; live mode available via flag only but no CLOB V2 gate | reference only for scanner/risk ideas; rewrite all execution |
| `PolyScripts/polymarket-market-maker-bot` | Market-making keeper with AMM/bands strategies | Some order ladder and cancellation strategy tests may be useful as abstract market-making references | Legacy `py-clob-client>=0.13.3`; V1 constructor; old USDC wording; direct private key use; random midpoint fallback; premium/support upsell | no | yes | not primary | no clear paper mode | yes | Private key in `.env`; live order placement/cancel loop; no CLOB V2 safety gate | ignore for production; optional strategy reference only |
| `PolyScripts/polymarket-arbitrage-trading-bot-pack-5min-15min-kalshi` | Bot-pack marketing repo | None for code; useful warning example of claims without source | No implementation source; premium upsell; screenshots/marketing only | no evidence | no source | no source | no | no | Encourages full-source purchase; unverifiable claims | ignore |
| `PolyScripts/polymarket-5min-15min-1hr-btc-arbitrage-trading-bot-rust` | Claimed Rust low-latency BTC up/down arbitrage bot | None for code; useful warning example | No `Cargo.toml` or source code in cloned repo; live instructions but no auditable implementation; premium/support upsell | no evidence | no source | no source | dry-run mentioned, no code | no | Requests trading credentials in `.env`; unverifiable 20ms/performance claims | ignore |

## Detailed Findings

### `chainstacklabs/polyclaw`

Relevant files inspected:

- `pyproject.toml`
- `README.md`
- `lib/clob_client.py`
- `lib/wallet_manager.py`
- `lib/contracts.py`
- `scripts/trade.py`

This is the only cloned repo already pinned to `py-clob-client-v2==1.0.0` and already discusses pUSD, V2 approvals, and USDC.e wrapping. That makes it the closest live-reference repo.

Do not copy the execution path directly. `lib/clob_client.py` explicitly mutates the SDK HTTP client to support `HTTPS_PROXY`/`HTTP_PROXY` and retries Cloudflare blocks. That conflicts with the compliance rule for this project. It also places live orders directly and uses a split-plus-sell flow where a failed CLOB sell can leave the user holding unwanted tokens. If we later reuse the split idea, it needs explicit orphan-token accounting, conservative slippage caps, and journal entries.

### `agent-next/polymarket-paper-trader`

Relevant files inspected:

- `pyproject.toml`
- `README.md`
- `pm_trader/orderbook.py`
- `pm_trader/engine.py`
- `pm_trader/api.py`
- `pm_trader/db.py`
- `tests/`

This is the strongest reusable component. `orderbook.py` already walks the ask side for buys and bid side for sells, supports FOK/FAK, records average fill price, shares, cost, slippage, partial fills, and fills by level. `engine.py` persists paper trades/positions in SQLite and has extensive tests.

Required migration work: its fee model still pulls `/fee-rate` and stores `fee_rate_bps`. For CLOB V2, the new project should treat this as a paper placeholder only and eventually source fee details from V2 market metadata (`getClobMarketInfo`) or SDK behavior.

### `suislanchez/polymarket-kalshi-weather-bot`

Relevant files inspected:

- `README.md`
- `.env.example`
- `requirements.txt`
- `backend/core/signals.py`
- `backend/core/weather_signals.py`
- `backend/data/btc_markets.py`
- `backend/data/weather_markets.py`
- `backend/api/main.py`

Good reference for signal ideas, not execution. BTC logic includes 5-minute slug generation, time-window filters, RSI, momentum, VWAP deviation, SMA crossover, market skew, and convergence checks. Weather logic uses ensemble-member distribution and clips extreme probabilities instead of allowing 0/1 bets.

Main issue: Polymarket pricing is based on Gamma `outcomePrices`, not executable CLOB book levels. The simulation inserts trades directly from signal price and size rather than simulating fills against an orderbook.

### `yangyuan-zhen/PolyWeather`

Relevant files inspected:

- `README.md`
- `pyproject.toml`
- `requirements.txt`
- `src/data_collection/polymarket_readonly.py`
- `tests/test_polymarket_readonly.py`

Best weather-domain reference. It has explicit settlement-oriented bucket mapping, model probability vs market-implied price separation, and understands CLOB public semantics: BUY is executable ask and SELL is executable bid. It also computes quarter-Kelly as a read-only sizing diagnostic.

Main caveats: it is a large AGPL product, not a trading library. Reuse concepts, not code. It also has unrelated payment/onchain flows and generic proxy config, which should not be part of this project.

### `arkyu2077/polyclaw`

Relevant files inspected:

- `README.md`
- `.env.example`
- `requirements.txt`
- `pyproject.toml`
- `src/edge_calculator.py`
- `src/order_executor.py`
- `src/position_manager.py`
- `src/position_tracker.py`
- `src/decision_journal.py`
- `tests/`

Useful for scanner architecture, journal design, and filters: expiry checks, lottery-ticket rejection, absurd-edge rejection, max order size, daily loss, open-position caps, and stale order cleanup. It has meaningful unit tests.

All live execution must be rejected or rewritten. It depends on legacy `py_clob_client`, stores CLOB creds in `.env`, uses USDC.e terminology, uses V1 constructor style, and estimates fees manually.

### PolyScripts Repos

The market-maker repo has actual Python code and tests, but it is legacy V1 and directly places/cancels live orders. The other two optional repos are primarily marketing/screenshot repos without auditable implementation source. They should not influence the production base.

## Final Reuse Decision

Reuse concepts only:

- From `agent-next/polymarket-paper-trader`: orderbook fill simulation, SQLite paper ledger, FOK/FAK semantics, tests.
- From `chainstacklabs/polyclaw`: CLOB V2 package target, pUSD/V2 awareness, high-level wallet/market client shape.
- From `yangyuan-zhen/PolyWeather`: weather bucket mapping, CLOB public price semantics, model-vs-market separation, quarter-Kelly diagnostic.
- From `suislanchez/polymarket-kalshi-weather-bot`: BTC microstructure indicators and weather ensemble signal shape.
- From `arkyu2077/polyclaw`: news scanner shape, risk filters, decision journal ideas.

Rewrite completely:

- Live executor.
- CLOB client wrapper.
- Risk manager.
- Order validator.
- Fee handling.
- Secrets handling.
- Compliance/access failure handling.

Ignore:

- PolyScripts marketing-only repos.
- Any code path requiring proxy/IP-rotation, Cloudflare evasion, old `py_clob_client`, or old V1 order fields for live execution.
