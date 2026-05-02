# Hermes Polymarket CLOB V2 Agent - Stage 1 Prompt

## Objective

Build the current Polymarket trading project by cloning and auditing existing open-source repositories, then designing a clean CLOB V2-compatible project. Do not blindly run someone else's bot. Reuse only sound parts after audit.

Stage 1 scope:

1. Clone and inspect relevant repos.
2. Audit logic, dependencies, safety, and CLOB compatibility.
3. Produce `repo_audit.md`.
4. Propose the minimal architecture for the new CLOB V2 project.
5. Do not implement live trading yet.
6. Do not ask for private keys.

## Non-Negotiable Rules

### CLOB V2 Only

- Python execution must use `py-clob-client-v2`.
- Do not use legacy `py-clob-client` for live execution.
- Do not use old V1 order fields such as `feeRateBps`, `nonce`, or `taker`.
- Use pUSD collateral assumptions, not old USDC.e assumptions, except where wrapping USDC.e to pUSD is documented as a manual funding step.
- Any cloned repo using old `py-clob-client` is logic-reference-only unless migrated.

### No Unsafe Live Trading

- Default mode must be `paper`.
- `dry-run` must be available.
- `live` must require `ALLOW_LIVE_TRADING=true`, explicit `--live`, max order size cap, daily loss limit, max open positions, and max per-market exposure.
- Never place a real order during setup, audit, tests, or dry-run.

### Secrets Safety

- Never ask for private keys in chat.
- Use `.env` only.
- Create `.env.example` with placeholders.
- Never print, log, commit, or store private keys or API secrets.
- If a private key is missing, run public-data and paper-only mode.

### Compliance and Access

- Do not implement geo-restriction bypassing.
- Do not implement Cloudflare or IP-ban evasion.
- Fail closed if the API rejects trading due to access, jurisdiction, or Cloudflare issues.
- Do not add proxy logic unless explicitly requested and confirmed compliant.

### Trading Logic

- Use Quarter-Kelly sizing, not full Kelly.
- Use real CLOB orderbook prices for executable pricing.
- Do not treat Gamma `outcomePrices` as bid/ask.
- Prefer best ask for buy simulation and best bid for sell simulation.
- Account for spread, slippage, liquidity, fees, min order size, and exposure caps.
- Do not trust LLM probability estimates directly.
- Reject absurd edges, illiquid markets, near-expiry markets, stale markets, and lottery-ticket prices.

## Repos To Clone And Audit

Primary:

- `chainstacklabs/polyclaw`: https://github.com/chainstacklabs/polyclaw
- `agent-next/polymarket-paper-trader`: https://github.com/agent-next/polymarket-paper-trader
- `suislanchez/polymarket-kalshi-weather-bot`: https://github.com/suislanchez/polymarket-kalshi-weather-bot
- `yangyuan-zhen/PolyWeather`: https://github.com/yangyuan-zhen/PolyWeather
- `arkyu2077/polyclaw`: https://github.com/arkyu2077/polyclaw

Optional warning examples:

- `PolyScripts/polymarket-market-maker-bot`
- `PolyScripts/polymarket-arbitrage-trading-bot-pack-5min-15min-kalshi`
- `PolyScripts/polymarket-5min-15min-1hr-btc-arbitrage-trading-bot-rust`

X-post inspiration candidates to consider later, not trusted without audit:

- `JLowo/gengar_polymarket_bot`
- `joicodev/polymarket-bot`
- `aulekator/Polymarket-BTC-15-Minute-Trading-Bot`
- `djienne/Polymarket-bot`
- `Parallax-Trading/Orbital-Alpha`

## Audit Questions

For each repo inspect:

- README
- `pyproject.toml`, `requirements.txt`, `package.json`, or `Cargo.toml`
- core execution files
- risk/sizing files
- signal generation files
- tests
- private-key and order-placement handling

`repo_audit.md` must include:

- repo
- purpose
- good parts to reuse
- bad parts to avoid
- CLOB V2 compatible?
- uses old `py-clob-client`?
- treats Gamma `outcomePrices` as bid/ask?
- has paper mode?
- has tests?
- security concerns
- final decision

## Verified Current Polymarket Constraints

Checked against official Polymarket docs on 2026-05-01:

- CLOB V2 migration go-live: 2026-04-28.
- SDK package: `py-clob-client-v2`.
- Production host after cutover: `https://clob.polymarket.com`.
- Collateral: pUSD.
- Removed live order fields: `feeRateBps`, `nonce`, `taker`.
- Fees are operator-set at match time and should not be embedded in signed orders.
- V2 market metadata should be read with `getClobMarketInfo(conditionID)` or equivalent.

Source: https://docs.polymarket.com/v2-migration
