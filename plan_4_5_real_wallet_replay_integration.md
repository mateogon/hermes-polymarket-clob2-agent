# Plan 4.5: Real Wallet Replay Integration

Status: implemented as a research-only bridge before crypto latency measurement.

Rules:

- No live trading.
- No private keys.
- No order posting.
- Wallet-flow remains paper/research only.
- Replay results are labeled `historical_approx` unless backed by local L2 snapshots.

Implemented scope:

- Persist fetched Polymarket Data API wallet trades in `wallet_observed_trades`.
- Deduplicate observed wallet trades on wallet, transaction hash, market, asset, side, and timestamp.
- Make `wallet-flow fetch` store trades and report fetched/inserted/duplicate counts.
- Make `wallet-flow replay` load persisted trades instead of replaying an empty list.
- Refuse replay with a clear message when no persisted trades exist.
- Use `ReplayRunConfig.exit_model` explicitly.
- Keep `leader_exit` functional when a later sell is observed.
- Mark `resolution_exit` as pending with `resolution_data_missing` until resolution data is wired.
- Mark `risk_exit` as pending with `price_path_missing` until local price paths exist.
- Add historical-approx data-quality notes to replay summaries.
- Record each replay as a `StrategyExperimentRecord`.
- Write minimal replay artifacts under `artifacts/runs/<run_id>/`.
- Create inactive candidate semantic memories when replay evidence is large enough.
- Persist wallet scores and make leaderboard read from stored scores.
- Add tests for storage, CLI integration, exit-model honesty, experiment/memory creation, score persistence, and import safety.

Remaining before Plan 5:

- Run real `wallet-flow fetch` for target wallets.
- Inspect historical-approx replay output and confirm the Data API trade shape remains stable.
- Decide whether to wire resolution data before or after crypto latency measurement.
- Build local L2 recorder before treating replay slippage as executable.
