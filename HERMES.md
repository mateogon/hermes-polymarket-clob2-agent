# Hermes Research Campaign Protocol

Hermes may run only paper campaigns.

Forbidden:
- live orders
- private keys
- `ALLOW_LIVE_TRADING=true`
- `live_executor.py` edits
- risk cap increases

Campaign steps:
1. Run `pytest`, `compileall`, and the live gate.
2. Check watchlist health.
3. Run healthy-only paper campaigns at `0.01` and `0.015`.
4. Generate `campaign-summary`.
5. Run `strategy-arena`.
6. Run `evidence-dashboard`.
7. Summarize total signals, total positions, net PnL, dominant rejects, warnings, and readiness.
8. Never recommend live unless pre-live audit passes.

Hermes prompt:

```text
Run the safe paper campaign protocol.

Do not live trade.
Do not ask for private keys.
Do not modify live_executor.py.
Use only healthy watchlist markets.
Run 0.01 and 0.015 thresholds for 900 seconds each.
Generate campaign summary, strategy arena, and evidence dashboard.
Summarize whether evidence improved.
```
