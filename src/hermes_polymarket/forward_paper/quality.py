"""Quality warnings for forward paper runs."""

from __future__ import annotations


def forward_paper_quality_warnings(
    *,
    signals: int,
    closed_positions: int,
    min_move_pct: float,
    min_strategy_threshold_pct: float = 0.03,
) -> list[str]:
    warnings: list[str] = []
    if signals == 0:
        warnings.append("no_signals_generated")
    if closed_positions == 0:
        warnings.append("no_closed_positions")
    if signals < 30:
        warnings.append("small_signal_sample")
    if closed_positions < 20:
        warnings.append("small_closed_position_sample")
    if min_move_pct < min_strategy_threshold_pct:
        warnings.append("exploratory_threshold_not_strategy_threshold")
    return warnings
