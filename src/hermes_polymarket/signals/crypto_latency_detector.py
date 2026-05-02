"""External crypto move detector for latency measurement."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from hermes_polymarket.signals.source_consensus import ConsensusPrice


@dataclass(frozen=True)
class CryptoLatencyEvent:
    event_id: str
    symbol: str
    external_move_pct: float
    detected_ts_ms: int
    reference_price: float
    current_price: float


def detect_external_move(
    *,
    symbol: str,
    previous: ConsensusPrice,
    current: ConsensusPrice,
    min_move_pct: float,
    detected_ts_ms: int,
) -> CryptoLatencyEvent | None:
    if previous.price <= 0:
        return None

    move_pct = (current.price - previous.price) / previous.price * 100.0
    if abs(move_pct) < min_move_pct:
        return None

    return CryptoLatencyEvent(
        event_id=f"crypto_lat_{uuid4().hex[:12]}",
        symbol=symbol,
        external_move_pct=move_pct,
        detected_ts_ms=detected_ts_ms,
        reference_price=previous.price,
        current_price=current.price,
    )
