"""Simple overfit and evidence-quality warnings."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OverfitInputs:
    sample_size: int
    experiment_count: int
    free_parameters_changed: int = 0
    category_pnl: dict[str, float] | None = None
    forward_paper_trades: int = 0
    out_of_sample_roi: float | None = None
    in_sample_roi: float | None = None


def overfit_warnings(inputs: OverfitInputs) -> list[str]:
    warnings: list[str] = []
    if inputs.sample_size < 100:
        warnings.append("small_sample")
    if inputs.experiment_count > max(10, inputs.sample_size // 5):
        warnings.append("too_many_experiments")
    if inputs.free_parameters_changed > 5:
        warnings.append("too_many_free_parameters")
    if inputs.forward_paper_trades < 50:
        warnings.append("missing_forward_paper_confirmation")
    if _category_concentrated(inputs.category_pnl or {}):
        warnings.append("category_concentration")
    if inputs.in_sample_roi is not None and inputs.out_of_sample_roi is not None:
        if inputs.in_sample_roi > 0 and inputs.out_of_sample_roi < inputs.in_sample_roi * 0.5:
            warnings.append("out_of_sample_degradation")
    return warnings


def _category_concentrated(category_pnl: dict[str, float]) -> bool:
    positives = [value for value in category_pnl.values() if value > 0]
    total = sum(positives)
    return bool(total and max(positives) / total > 0.8 and len(positives) > 1)

