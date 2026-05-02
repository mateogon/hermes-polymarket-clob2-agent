"""Replay quality warnings for research reports."""

from __future__ import annotations

from dataclasses import dataclass

from hermes_polymarket.backtest.wallet_replay_models import ReplayTradeResult


@dataclass(frozen=True)
class ReplayQualityReport:
    warnings: list[str]
    details: dict

    def to_dict(self) -> dict:
        return {"warnings": self.warnings, "details": self.details}


def replay_quality_warnings(results: list[ReplayTradeResult]) -> ReplayQualityReport:
    closed = [row for row in results if row.status == "closed" and row.pnl is not None]
    skipped = [row for row in results if row.status == "skipped"]
    pending = [row for row in results if row.status == "pending"]

    warnings: list[str] = []
    details = {
        "closed": len(closed),
        "skipped": len(skipped),
        "pending": len(pending),
        "total": len(results),
    }

    if not closed:
        warnings.append("no_closed_trades")
        return ReplayQualityReport(warnings, details)

    if len(closed) < 30:
        warnings.append("small_sample")

    positive = [row.pnl for row in closed if (row.pnl or 0.0) > 0]
    total_positive = sum(positive)
    if total_positive > 0:
        top_share = max(positive) / total_positive
        details["top_positive_trade_share"] = top_share
        if top_share > 0.8:
            warnings.append("one_hit_wonder")

    if len(pending) > len(closed) * 2:
        warnings.append("too_many_pending")
    if len(skipped) > len(closed) * 2:
        warnings.append("too_many_skipped")

    by_delay: dict[int, list[ReplayTradeResult]] = {}
    for row in closed:
        by_delay.setdefault(row.delay_seconds, []).append(row)
    roi_by_delay = {
        delay: sum((row.roi or 0.0) for row in rows) / len(rows)
        for delay, rows in by_delay.items()
        if rows
    }
    details["roi_by_delay"] = roi_by_delay

    if 0 in roi_by_delay and 120 in roi_by_delay and roi_by_delay[120] > roi_by_delay[0] * 1.5 and roi_by_delay[120] > 0:
        warnings.append("suspicious_delay_curve")

    return ReplayQualityReport(warnings, details)
