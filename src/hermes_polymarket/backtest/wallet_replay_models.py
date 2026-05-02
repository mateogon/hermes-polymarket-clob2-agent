"""Data models for wallet-flow replay."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ExitModel(str, Enum):
    LEADER_EXIT = "leader_exit"
    RESOLUTION_EXIT = "resolution_exit"
    RISK_EXIT = "risk_exit"


@dataclass(frozen=True)
class ReplayRunConfig:
    wallet: str
    delays_seconds: tuple[int, ...] = (0, 2, 5, 15, 30, 120, 600)
    mode: str = "historical_approx"
    paper_amount_usd: float = 5.0
    max_worse_entry_cents: float = 2.0
    max_delay_seconds: int = 600
    exit_model: ExitModel = ExitModel.LEADER_EXIT
    data_quality: str = "historical_approx"

    def __post_init__(self) -> None:
        if self.mode not in {"historical_approx", "local_l2"}:
            raise ValueError("mode must be historical_approx or local_l2")
        if self.paper_amount_usd <= 0:
            raise ValueError("paper_amount_usd must be positive")


@dataclass(frozen=True)
class ReplayTradeResult:
    replay_trade_id: str
    run_id: str
    wallet: str
    condition_id: str
    asset_id: str
    outcome: str
    delay_seconds: int
    exit_model: ExitModel
    status: str
    entry_time: int | None = None
    entry_price: float | None = None
    leader_entry_price: float | None = None
    exit_time: int | None = None
    exit_price: float | None = None
    pnl: float | None = None
    roi: float | None = None
    worse_entry_cents: float | None = None
    skipped_reason: str | None = None
    category: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def to_storage_dict(self) -> dict[str, Any]:
        import json

        return {
            "replay_trade_id": self.replay_trade_id,
            "run_id": self.run_id,
            "wallet": self.wallet,
            "condition_id": self.condition_id,
            "asset_id": self.asset_id,
            "outcome": self.outcome,
            "delay_seconds": self.delay_seconds,
            "entry_time": self.entry_time,
            "entry_price": self.entry_price,
            "leader_entry_price": self.leader_entry_price,
            "exit_time": self.exit_time,
            "exit_price": self.exit_price,
            "exit_model": self.exit_model.value,
            "status": self.status,
            "pnl": self.pnl,
            "roi": self.roi,
            "worse_entry_cents": self.worse_entry_cents,
            "skipped_reason": self.skipped_reason,
            "category": self.category,
            "payload_json": json.dumps(self.payload, sort_keys=True),
        }


@dataclass(frozen=True)
class WalletScore:
    wallet: str
    score: float
    components: dict[str, float]
    sample_size: int

