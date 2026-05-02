"""Forward paper signal contracts."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ForwardPaperSignal:
    signal_id: str
    run_id: str
    symbol: str
    condition_id: str | None
    token_id: str
    outcome: str
    external_move_ts_ms: int
    amount_usd: float
    final_action: str
    data_quality: str = "paper_live"
    avg_price: float | None = None
    shares: float | None = None
    best_bid: float | None = None
    best_ask: float | None = None
    spread: float | None = None
