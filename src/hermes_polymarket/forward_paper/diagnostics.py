"""Explainability helpers for forward paper signals."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

from hermes_polymarket.backtest.local_l2_lookup import reconstruct_book_at
from hermes_polymarket.config import Settings
from hermes_polymarket.polymarket.orderbook import simulate_buy_fill
from hermes_polymarket.polymarket.types import FillResult, OrderBook, TradeProposal
from hermes_polymarket.risk.exposure import ExposureSnapshot
from hermes_polymarket.risk.risk_manager import RiskManager, executable_depth_usd
from hermes_polymarket.storage.db import Database


def signal_by_id(db: Database, signal_id: str) -> dict[str, Any] | None:
    row = db.conn.execute(
        """
        SELECT *
        FROM forward_paper_signals
        WHERE signal_id = ?
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (signal_id,),
    ).fetchone()
    return dict(row) if row else None


def _payload(signal: dict[str, Any]) -> dict[str, Any]:
    try:
        value = json.loads(signal.get("payload_json") or "{}")
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        return {}


def _midpoint(best_bid: float | None, best_ask: float | None) -> float | None:
    if best_bid is None or best_ask is None:
        return None
    return (best_bid + best_ask) / 2.0


def _slippage(avg_price: float | None, midpoint: float | None) -> float | None:
    if avg_price is None or midpoint in (None, 0):
        return None
    return (avg_price - midpoint) / midpoint


def top_levels(book: OrderBook, *, side: str, limit: int = 5) -> list[dict[str, float]]:
    levels = book.bids if side == "bid" else book.asks
    ordered = sorted(levels, key=lambda level: level.price, reverse=side == "bid")
    return [{"price": level.price, "size": level.size, "value_usd": level.price * level.size} for level in ordered[:limit]]


def depth_within_pct(book: OrderBook, *, side: str, pct: float) -> float:
    midpoint = book.midpoint
    if midpoint is None:
        return 0.0
    if side.lower() == "sell":
        floor = midpoint * (1.0 - pct)
        return sum(level.price * level.size for level in book.bids if level.price >= floor)
    ceiling = midpoint * (1.0 + pct)
    return sum(level.price * level.size for level in book.asks if level.price <= ceiling)


def shadow_risk_diagnostics(
    *,
    settings: Settings,
    proposal: TradeProposal,
    book: OrderBook,
    fill: FillResult,
    exposure: ExposureSnapshot,
) -> dict[str, str]:
    diagnostics: dict[str, str] = {}
    for max_slippage in (0.02, 0.03, 0.05):
        for min_edge in (0.03, 0.01):
            shadow_settings = replace(settings, max_slippage=max_slippage, min_edge=min_edge)
            decision = RiskManager(shadow_settings).evaluate(proposal, book, fill, exposure)
            key = f"max_slippage={max_slippage:.2f},min_edge={min_edge:.2f}"
            diagnostics[key] = "allowed_shadow_only" if decision.allowed else f"rejected:{decision.reason}"
    return diagnostics


def l2_context_for_signal(db: Database, signal: dict[str, Any], *, levels: int = 5) -> dict[str, Any]:
    token_id = signal.get("token_id")
    ts_ms = signal.get("external_move_ts_ms")
    if not token_id or ts_ms is None:
        return {
            "signal_id": signal.get("signal_id"),
            "book_found": False,
            "reason": "signal_missing_token_or_timestamp",
        }

    state = reconstruct_book_at(db, token_id=str(token_id), target_ts_ms=int(ts_ms))
    if state is None or str(token_id) not in state.by_token:
        return {
            "signal_id": signal.get("signal_id"),
            "book_found": False,
            "token_id": token_id,
            "timestamp_ms": int(ts_ms),
            "reason": "no_l2_book_at_timestamp",
        }

    book = state.by_token[str(token_id)].as_orderbook()
    return {
        "signal_id": signal.get("signal_id"),
        "book_found": True,
        "token_id": token_id,
        "timestamp_ms": int(ts_ms),
        "best_bid": book.best_bid,
        "best_ask": book.best_ask,
        "spread": book.spread,
        "top_bids": top_levels(book, side="bid", limit=levels),
        "top_asks": top_levels(book, side="ask", limit=levels),
        "depth_within_2pct": depth_within_pct(book, side="buy", pct=0.02),
        "depth_within_5pct": depth_within_pct(book, side="buy", pct=0.05),
    }


def explain_forward_signal(db: Database, signal_id: str, settings: Settings) -> dict[str, Any]:
    signal = signal_by_id(db, signal_id)
    if signal is None:
        return {"found": False, "signal_id": signal_id}

    payload = _payload(signal)
    best_bid = signal.get("best_bid")
    best_ask = signal.get("best_ask")
    avg_price = signal.get("avg_price")
    midpoint = payload.get("midpoint")
    if midpoint is None:
        midpoint = _midpoint(best_bid, best_ask)
    slippage = payload.get("slippage")
    if slippage is None:
        slippage = _slippage(avg_price, midpoint)

    why_by_reason = {
        "max_slippage": "Simulated entry slippage exceeded configured max_slippage.",
        "min_edge": "Adjusted edge was below configured min_edge.",
        "min_liquidity": "Executable orderbook depth was below configured minimum.",
        "direction_mapping_missing": "No explicit up/down token mapping was available.",
        "direction_mapping_ambiguous": "More than one directional token matched the signal.",
        "no_executable_fill": "No executable local L2 fill was available at the signal timestamp.",
    }
    risk_reason = signal.get("risk_reason")
    context = l2_context_for_signal(db, signal)
    shadow_risk = payload.get("shadow_risk") or {}

    if context.get("book_found") and signal.get("token_id"):
        state = reconstruct_book_at(db, token_id=str(signal["token_id"]), target_ts_ms=int(signal["external_move_ts_ms"]))
        if state is not None and str(signal["token_id"]) in state.by_token:
            book = state.by_token[str(signal["token_id"])].as_orderbook()
            fill = simulate_buy_fill(book, float(signal.get("amount_usd") or 0.0), order_type="fok")
            proposal = TradeProposal(
                market_id=str(signal.get("condition_id") or ""),
                condition_id=str(signal.get("condition_id") or ""),
                token_id=str(signal.get("token_id") or ""),
                outcome=str(signal.get("outcome") or ""),
                side="buy",
                amount_usd=float(signal.get("amount_usd") or 0.0),
                model_probability=float(signal.get("model_probability") or 0.0),
                confidence=float(payload.get("confidence") or 0.35),
                reason="forward paper explain shadow diagnostics",
            )
            shadow_risk = shadow_risk or shadow_risk_diagnostics(
                settings=settings,
                proposal=proposal,
                book=book,
                fill=fill,
                exposure=ExposureSnapshot(bankroll=settings.initial_bankroll),
            )

    return {
        "found": True,
        "signal_id": signal_id,
        "run_id": signal.get("run_id"),
        "final_action": signal.get("final_action"),
        "risk_reason": risk_reason,
        "why": why_by_reason.get(str(risk_reason), payload.get("risk_explanation") or "No specific explanation available."),
        "inputs": {
            "external_move_pct": signal.get("external_move_pct"),
            "direction": signal.get("direction"),
            "outcome": signal.get("outcome"),
            "best_bid": best_bid,
            "best_ask": best_ask,
            "midpoint": midpoint,
            "avg_price": avg_price,
            "spread": signal.get("spread"),
            "slippage": slippage,
            "max_slippage": payload.get("max_slippage", settings.max_slippage),
            "depth_within_slippage_usd": payload.get("depth_within_slippage_usd"),
            "min_orderbook_depth_usd": settings.min_orderbook_depth_usd,
            "model_probability": signal.get("model_probability"),
            "min_edge": payload.get("min_edge", settings.min_edge),
            "fill_status": signal.get("fill_status"),
        },
        "risk_explanation": payload.get("risk_explanation"),
        "payload": payload,
        "l2_context": context,
        "shadow_risk": shadow_risk,
    }
