"""Threshold calibration counters for forward paper runs."""

from __future__ import annotations

from collections import Counter


class ThresholdCalibration:
    def __init__(self, thresholds_pct: list[float]):
        self.thresholds = thresholds_pct
        self.hits: Counter[str] = Counter()

    def observe_move(self, move_pct: float) -> None:
        magnitude = abs(move_pct)
        for threshold in self.thresholds:
            if magnitude >= threshold:
                self.hits[str(threshold)] += 1

    def to_dict(self) -> dict[str, int]:
        return dict(self.hits)
