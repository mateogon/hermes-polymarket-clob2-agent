# Hermes Polymarket CLOB V2 Agent

Local project workspace for a safe Polymarket CLOB V2 trading agent.

Current stage: Phase 1 audit only.

Created artifacts:

- `docs/stage_1_prompt.md` - saved project prompt and constraints
- `repo_audit.md` - cloned repo audit and reuse decisions
- `design.md` - minimal architecture proposal
- `external_repos/` - cloned reference repos

Live trading is not implemented and must remain disabled until paper mode, dry-run, tests, CLOB V2 validation, and explicit live gates are complete.

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
