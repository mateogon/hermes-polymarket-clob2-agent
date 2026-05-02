# Plan Learning Loop

Goal: add a safe, reproducible learning and audit foundation before wallet replay, crypto latency experiments, or any live execution work.

Rules:

- No live trading.
- No private keys.
- No auto-modification of live executor or live risk caps.
- Hypotheses and candidate rules can be generated, but only paper-mode activation is allowed.
- Every learning output must be reproducible from stored data.

Learning path:

```text
observe -> journal -> evaluate -> reflect -> hypothesize -> replay -> paper -> promote/reject
```

Initial implementation scope:

1. Structured journal schemas for signals, trades, counterfactuals, reflections, hypotheses, experiments, and promotion decisions.
2. SQLite persistence for decision journal, lifecycle records, hypotheses, memories, and experiment records.
3. Metrics for PnL, ROI, drawdown, calibration, slippage, copyability, rejected reasons, and category performance.
4. Overfit warnings for small samples, too many parameter sweeps, missing forward paper, category concentration, one-hit-wonder patterns, and out-of-sample degradation.
5. Daily/weekly reports that render even with an empty database.
6. CLI commands for reports, hypotheses, memory search, paper-only promotion, and rule retirement.

Promotion invariant:

```text
candidate_rule -> paper_active is possible only with --paper-only and human approval.
candidate_rule -> live_active is not supported.
```

Future work:

- `plan_4`: wallet replay and exit model.
- `plan_5`: crypto latency measurement.
- `plan_6`: dashboard/reporting.
- `plan_7`: paper strategy arena.
- `plan_8`: pre-live safety audit.
