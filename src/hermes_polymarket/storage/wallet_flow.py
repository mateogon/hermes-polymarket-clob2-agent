"""Wallet-flow metrics from persisted normalized events."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, asdict
from typing import Any

from hermes_polymarket.data_sources.base import DataEvent, EventType, now_ms
from hermes_polymarket.signals.wallet_flow_signal import CopyabilityDecision
from hermes_polymarket.data_sources.polymarket_data_api import WalletTrade
from hermes_polymarket.storage.db import Database


WALLET_FLOW_EVENT = "wallet_flow"


@dataclass(frozen=True)
class WalletFlowMetrics:
    observed_trades: int = 0
    copyable_trades: int = 0
    rejected_trades: int = 0
    average_detection_delay: float = 0.0
    average_worse_entry_cents: float = 0.0
    paper_pnl: float = 0.0
    max_drawdown: float = 0.0
    best_category: str | None = None
    worst_category: str | None = None
    rejected_by_reason: dict[str, int] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def wallet_flow_event(
    trade: WalletTrade,
    decision: CopyabilityDecision,
    *,
    wallet_name: str,
    categories: tuple[str, ...] = (),
    paper_pnl: float = 0.0,
) -> DataEvent:
    return DataEvent(
        source=WALLET_FLOW_EVENT,
        event_type=EventType.WALLET_TRADE,
        event_ts_ms=trade.timestamp * 1000,
        received_ts_ms=now_ms(),
        key=trade.wallet.lower(),
        payload={
            "wallet_name": wallet_name,
            "wallet": trade.wallet,
            "condition_id": trade.condition_id,
            "asset_id": trade.asset_id,
            "slug": trade.slug,
            "outcome": trade.outcome,
            "side": trade.side,
            "leader_price": trade.price,
            "size": trade.size,
            "notional_usd": trade.notional_usd,
            "copyable": decision.copyable,
            "reason": decision.reason,
            "our_avg_price": decision.our_avg_price,
            "worse_by_cents": decision.worse_by_cents,
            "latency_seconds": decision.latency_seconds,
            "paper_amount_usd": decision.paper_amount_usd,
            "paper_pnl": paper_pnl,
            "categories": list(categories),
            "tx_hash": trade.tx_hash,
        },
    )


def record_wallet_flow_decision(
    db: Database,
    trade: WalletTrade,
    decision: CopyabilityDecision,
    *,
    wallet_name: str,
    categories: tuple[str, ...] = (),
    paper_pnl: float = 0.0,
) -> int:
    return db.insert_data_event(wallet_flow_event(trade, decision, wallet_name=wallet_name, categories=categories, paper_pnl=paper_pnl))


def wallet_flow_metrics(db: Database, *, wallet: str | None = None) -> WalletFlowMetrics:
    rows = _wallet_rows(db.conn, wallet=wallet)
    observed = len(rows)
    if observed == 0:
        return WalletFlowMetrics(rejected_by_reason={})

    payloads = [json.loads(row["payload_json"]) for row in rows]
    copyable = [p for p in payloads if p.get("copyable")]
    rejected = [p for p in payloads if not p.get("copyable")]
    delays = [float(p["latency_seconds"]) for p in payloads if p.get("latency_seconds") is not None]
    worse = [float(p["worse_by_cents"]) for p in copyable if p.get("worse_by_cents") is not None]
    pnl_series = [float(p.get("paper_pnl") or 0.0) for p in payloads]
    category_pnl: dict[str, float] = {}
    rejected_by_reason: dict[str, int] = {}

    for payload in payloads:
        reason = str(payload.get("reason") or "unknown")
        if not payload.get("copyable"):
            rejected_by_reason[reason] = rejected_by_reason.get(reason, 0) + 1
        for category in payload.get("categories") or []:
            category_pnl[str(category)] = category_pnl.get(str(category), 0.0) + float(payload.get("paper_pnl") or 0.0)

    best_category = max(category_pnl, key=category_pnl.get) if category_pnl else None
    worst_category = min(category_pnl, key=category_pnl.get) if category_pnl else None

    return WalletFlowMetrics(
        observed_trades=observed,
        copyable_trades=len(copyable),
        rejected_trades=len(rejected),
        average_detection_delay=sum(delays) / len(delays) if delays else 0.0,
        average_worse_entry_cents=sum(worse) / len(worse) if worse else 0.0,
        paper_pnl=sum(pnl_series),
        max_drawdown=_max_drawdown(pnl_series),
        best_category=best_category,
        worst_category=worst_category,
        rejected_by_reason=rejected_by_reason,
    )


def _wallet_rows(conn: sqlite3.Connection, *, wallet: str | None) -> list[sqlite3.Row]:
    if wallet:
        return list(
            conn.execute(
                """
                SELECT * FROM data_events
                WHERE source = ? AND event_type = ? AND event_key = ?
                ORDER BY received_ts_ms, id
                """,
                (WALLET_FLOW_EVENT, EventType.WALLET_TRADE.value, wallet.lower()),
            )
        )
    return list(
        conn.execute(
            """
            SELECT * FROM data_events
            WHERE source = ? AND event_type = ?
            ORDER BY received_ts_ms, id
            """,
            (WALLET_FLOW_EVENT, EventType.WALLET_TRADE.value),
        )
    )


def _max_drawdown(pnl_series: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for pnl in pnl_series:
        equity += pnl
        peak = max(peak, equity)
        max_dd = min(max_dd, equity - peak)
    return abs(max_dd)

