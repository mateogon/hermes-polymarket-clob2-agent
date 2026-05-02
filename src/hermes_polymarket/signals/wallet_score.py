"""Wallet scoring for replay and paper-copy research."""

from __future__ import annotations

from collections import Counter

from hermes_polymarket.backtest.wallet_replay_models import ReplayTradeResult, WalletScore


def score_wallet(wallet: str, results: list[ReplayTradeResult]) -> WalletScore:
    closed = [row for row in results if row.status == "closed"]
    warnings: list[str] = []
    if len(closed) < 30:
        warnings.append("small_sample")
    components = {
        "sample_size": _sample_size_score(len(closed)),
        "recent_performance": _recent_performance_score(closed),
        "drawdown": _drawdown_score(closed),
        "copy_delay_survival": _delay_survival_score(results),
        "category_focus": _category_focus_score(results),
        "entry_slippage": _entry_slippage_score(results),
        "exit_behavior": _exit_behavior_score(results),
        "style_drift": _style_drift_penalty(results),
        "one_hit_wonder": _one_hit_wonder_penalty(closed),
        "market_liquidity": _market_liquidity_penalty(results),
    }
    positive_keys = ["sample_size", "recent_performance", "drawdown", "copy_delay_survival", "category_focus", "entry_slippage", "exit_behavior"]
    penalty_keys = ["style_drift", "one_hit_wonder", "market_liquidity"]
    score = sum(components[key] for key in positive_keys) / len(positive_keys)
    score -= sum(components[key] for key in penalty_keys) / len(penalty_keys) * 0.35
    return WalletScore(wallet=wallet, score=max(0.0, min(1.0, score)), components=components, sample_size=len(closed), warnings=tuple(warnings))


def _sample_size_score(n: int) -> float:
    return min(1.0, n / 200.0)


def _recent_performance_score(results: list[ReplayTradeResult]) -> float:
    if not results:
        return 0.0
    recent = results[-50:]
    wins = sum(1 for row in recent if (row.pnl or 0.0) > 0)
    return wins / len(recent)


def _drawdown_score(results: list[ReplayTradeResult]) -> float:
    equity = 0.0
    peak = 0.0
    worst = 0.0
    for row in results:
        equity += row.pnl or 0.0
        peak = max(peak, equity)
        worst = min(worst, equity - peak)
    return max(0.0, 1.0 - abs(worst) / 50.0)


def _delay_survival_score(results: list[ReplayTradeResult]) -> float:
    delayed = [row for row in results if row.delay_seconds >= 15]
    if not delayed:
        return 0.0
    survived = [row for row in delayed if row.status == "closed" and (row.pnl or 0.0) > 0]
    return len(survived) / len(delayed)


def _category_focus_score(results: list[ReplayTradeResult]) -> float:
    categories = [row.category for row in results if row.category]
    if not categories:
        return 0.0
    counts = Counter(categories)
    return max(counts.values()) / len(categories)


def _entry_slippage_score(results: list[ReplayTradeResult]) -> float:
    values = [row.worse_entry_cents for row in results if row.worse_entry_cents is not None and row.status == "closed"]
    if not values:
        return 0.0
    avg = sum(values) / len(values)
    return max(0.0, 1.0 - avg / 5.0)


def _exit_behavior_score(results: list[ReplayTradeResult]) -> float:
    if not results:
        return 0.0
    closed = sum(1 for row in results if row.status == "closed")
    return closed / len(results)


def _style_drift_penalty(results: list[ReplayTradeResult]) -> float:
    categories = [row.category for row in results if row.category]
    if len(set(categories)) <= 1:
        return 0.0
    first_half = set(categories[: len(categories) // 2])
    second_half = set(categories[len(categories) // 2 :])
    return 1.0 if first_half and second_half and not first_half.intersection(second_half) else 0.3


def _one_hit_wonder_penalty(results: list[ReplayTradeResult]) -> float:
    if len(results) < 5:
        return 1.0
    total = sum(row.pnl or 0.0 for row in results)
    if total <= 0:
        return 0.5
    top = max(row.pnl or 0.0 for row in results)
    return 1.0 if top / total > 0.8 else 0.0


def _market_liquidity_penalty(results: list[ReplayTradeResult]) -> float:
    skips = [row for row in results if row.skipped_reason in {"entry_too_late_or_too_expensive", "no_price_at_delay"}]
    return len(skips) / len(results) if results else 0.0
