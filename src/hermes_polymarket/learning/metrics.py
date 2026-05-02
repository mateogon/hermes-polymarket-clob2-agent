"""Learning and strategy quality metrics."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Iterable


def net_pnl(pnls: Iterable[float]) -> float:
    return float(sum(pnls))


def roi(pnl: float, capital: float) -> float:
    return 0.0 if capital == 0 else pnl / capital


def profit_factor(pnls: Iterable[float]) -> float:
    values = list(pnls)
    gains = sum(v for v in values if v > 0)
    losses = abs(sum(v for v in values if v < 0))
    if losses == 0:
        return float("inf") if gains > 0 else 0.0
    return gains / losses


def max_drawdown(equity_changes: Iterable[float]) -> float:
    equity = 0.0
    peak = 0.0
    worst = 0.0
    for change in equity_changes:
        equity += change
        peak = max(peak, equity)
        worst = min(worst, equity - peak)
    return abs(worst)


def hit_rate(outcomes: Iterable[bool]) -> float:
    values = list(outcomes)
    return 0.0 if not values else sum(1 for value in values if value) / len(values)


def brier_score(probabilities: Iterable[float], outcomes: Iterable[bool]) -> float:
    pairs = list(zip(probabilities, outcomes))
    return 0.0 if not pairs else sum((p - float(o)) ** 2 for p, o in pairs) / len(pairs)


def log_loss(probabilities: Iterable[float], outcomes: Iterable[bool], eps: float = 1e-12) -> float:
    pairs = list(zip(probabilities, outcomes))
    if not pairs:
        return 0.0
    total = 0.0
    for p, outcome in pairs:
        p = min(1 - eps, max(eps, p))
        total += -(math.log(p) if outcome else math.log(1 - p))
    return total / len(pairs)


def calibration_by_bucket(probabilities: Iterable[float], outcomes: Iterable[bool], bucket_size: float = 0.1) -> list[dict]:
    buckets: dict[int, list[tuple[float, bool]]] = defaultdict(list)
    for p, outcome in zip(probabilities, outcomes):
        idx = min(int(p / bucket_size), int(1 / bucket_size) - 1)
        buckets[idx].append((p, outcome))
    result = []
    for idx in sorted(buckets):
        values = buckets[idx]
        result.append(
            {
                "bucket_low": idx * bucket_size,
                "bucket_high": (idx + 1) * bucket_size,
                "count": len(values),
                "avg_probability": sum(p for p, _ in values) / len(values),
                "realized_rate": sum(1 for _, outcome in values if outcome) / len(values),
            }
        )
    return result


def average(values: Iterable[float]) -> float:
    values = list(values)
    return 0.0 if not values else sum(values) / len(values)


def rejected_by_reason(reasons: Iterable[str]) -> dict[str, int]:
    return dict(Counter(reasons))


def grouped_sum(rows: Iterable[tuple[str, float]]) -> dict[str, float]:
    out: dict[str, float] = defaultdict(float)
    for key, value in rows:
        out[key] += value
    return dict(out)
