"""Backtest metrics."""

from __future__ import annotations


def roi(starting: float, ending: float) -> float:
    if starting == 0:
        return 0.0
    return (ending - starting) / starting

