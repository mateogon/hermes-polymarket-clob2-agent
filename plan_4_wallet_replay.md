# Plan 4: Wallet Replay And Exit Model

Goal: convert wallet-flow entry-copyability into replayable paper-copy analytics before any live trading work.

Rules:

- No live trading.
- No private keys.
- No order posting.
- Wallet-flow remains signal-only and paper-only.
- Replay results are approximate unless backed by locally recorded L2 snapshots.

Replay modes:

- `historical_approx`: uses Data API wallet trades and leader prices as approximation.
- `local_l2`: reserved for locally recorded orderbook snapshots.

Exit models:

- `leader_exit`: exit when the observed leader sells the same wallet/condition/asset.
- `resolution_exit`: payout 1 or 0 when a market resolution is known.
- `risk_exit`: TP/SL/timeout using observed or locally recorded prices.

Delay sweep:

```text
0s, 2s, 5s, 15s, 30s, 120s, 600s
```

Reports must include:

- observed trades
- replayed trades
- skipped trades by reason
- ROI by delay
- win rate by delay
- max drawdown by delay
- average worse-entry cents
- PnL by category
- best/worst category
- unresolved/pending count
- data_quality

Promotion invariant:

Replay can generate hypotheses and candidate paper rules only. It cannot place live orders or activate live rules.
