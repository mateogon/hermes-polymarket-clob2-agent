"""Multi-strike target-hit paper watcher.

This is research-only. It uses public Gamma/CLOB REST data and writes paper
signals/positions; it never places orders.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import time
from typing import Any
from uuid import uuid4

from hermes_polymarket.crypto.market_quality import evaluate_market_quality
from hermes_polymarket.crypto.market_universe import filter_universe_candidates, scan_market_universe
from hermes_polymarket.crypto.multi_strike_fair_value import fair_value_target_hit
from hermes_polymarket.crypto.multi_strike_market import parse_multi_strike_target
from hermes_polymarket.crypto.watchlist_seeding import current_reference_consensus
from hermes_polymarket.forward_paper.lifecycle import (
    ForwardPaperPosition,
    close_position,
    mark_position,
    should_exit_position,
    update_excursions,
)
from hermes_polymarket.forward_paper.models import ForwardPaperSignal
from hermes_polymarket.polymarket.clob_v2_client import ClobV2Client
from hermes_polymarket.polymarket.gamma_client import GammaClient
from hermes_polymarket.polymarket.types import OrderBook
from hermes_polymarket.storage.db import Database
from hermes_polymarket.storage.forward_positions import insert_forward_mark, insert_forward_run, insert_forward_signal, upsert_forward_position


@dataclass(frozen=True)
class MultiStrikePaperConfig:
    event_slug: str
    symbol: str
    amount_usd: float = 5.0
    edge_threshold: float = 0.08
    exit_edge_threshold: float = 0.02
    seconds: int = 3600
    mark_interval_seconds: int = 300
    annualized_vol: float = 0.80
    min_ask: float = 0.03
    max_ask: float = 0.60
    max_spread: float = 0.01
    edge_spread_buffer: float = 0.0
    take_profit_cents: float = 5.0
    stop_loss_cents: float = 5.0
    timeout_seconds: int = 3600
    close_open_on_end: bool = False
    max_positions: int = 1


def _seconds_to_expiry(row: dict[str, Any], now: datetime) -> float:
    if row.get("end_date"):
        with contextlib.suppress(ValueError):
            parsed = datetime.fromisoformat(str(row["end_date"]).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return max(1.0, (parsed - now).total_seconds())
    return 1.0


def _candidate_payload(
    *,
    row: dict[str, Any],
    book: OrderBook,
    current_price: float,
    annualized_vol: float,
) -> dict[str, Any] | None:
    target = parse_multi_strike_target(f"{row.get('question') or ''} {row.get('slug') or ''}", current_price=current_price)
    target_price = row.get("strike_price") or (target.target_price if target is not None else None)
    if target_price is None:
        return None
    now = datetime.now(timezone.utc)
    fv = fair_value_target_hit(
        current_price=current_price,
        target_price=float(target_price),
        seconds_to_expiry=_seconds_to_expiry(row, now),
        annualized_vol=annualized_vol,
    )
    quality = evaluate_market_quality(book).to_dict()
    best_ask = book.best_ask
    best_bid = book.best_bid
    edge = fv.probability_yes - best_ask if best_ask is not None else None
    return {
        **row,
        "target_price": float(target_price),
        "current_price": current_price,
        "fair_value": fv.to_dict(),
        "quality": quality,
        "best_bid": best_bid,
        "best_ask": best_ask,
        "spread": book.spread,
        "edge": edge,
    }


def select_multi_strike_candidate(
    *,
    event: dict[str, Any],
    clob: ClobV2Client,
    symbol: str,
    current_price: float,
    config: MultiStrikePaperConfig,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    universe = scan_market_universe(events=[event], markets=[], symbols={symbol})
    considered: list[dict[str, Any]] = []
    for row in filter_universe_candidates(universe, market_type="multi_strike_event", min_score=0.0, limit=500):
        if not row.get("active") or row.get("closed"):
            continue
        token_id = row.get("yes_token_id")
        if not token_id:
            considered.append({**row, "selected": False, "reject_reason": "missing_yes_token_id"})
            continue
        try:
            book = clob.get_orderbook(str(token_id))
            candidate = _candidate_payload(row=row, book=book, current_price=current_price, annualized_vol=config.annualized_vol)
        except Exception as exc:  # noqa: BLE001 - research CLI reports per-market failures.
            considered.append({**row, "selected": False, "reject_reason": f"book_error:{exc}"})
            continue
        if candidate is None:
            considered.append({**row, "selected": False, "reject_reason": "target_parse_failed"})
            continue
        reasons: list[str] = []
        if not candidate["quality"].get("allowed"):
            reasons.append(f"quality:{candidate['quality'].get('reason')}")
        best_ask = candidate.get("best_ask")
        if best_ask is None:
            reasons.append("no_best_ask")
        elif best_ask < config.min_ask or best_ask > config.max_ask:
            reasons.append("ask_outside_bounds")
        edge = candidate.get("edge")
        if edge is None or edge < config.edge_threshold:
            reasons.append("edge_below_threshold")
        spread = candidate.get("spread")
        if spread is None:
            reasons.append("no_spread")
        elif spread > config.max_spread:
            reasons.append("spread_above_max")
        if edge is not None and spread is not None and edge < spread + config.edge_spread_buffer:
            reasons.append("edge_below_spread_buffer")
        considered.append({**candidate, "selected": not reasons, "reject_reason": ",".join(reasons) if reasons else "ok"})

    selected = [row for row in considered if row.get("selected")]
    selected.sort(key=lambda row: float(row.get("edge") or -999.0), reverse=True)
    return (selected[0] if selected else None), considered


def _signal_row(signal: ForwardPaperSignal, *, direction: str, model_probability: float, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "signal_id": signal.signal_id,
        "run_id": signal.run_id,
        "symbol": signal.symbol,
        "condition_id": signal.condition_id,
        "token_id": signal.token_id,
        "outcome": signal.outcome,
        "direction": direction,
        "external_move_ts_ms": signal.external_move_ts_ms,
        "external_move_pct": None,
        "final_action": signal.final_action,
        "risk_reason": None if signal.final_action == "paper_fill" else signal.final_action,
        "fill_status": "filled" if signal.final_action == "paper_fill" else "rejected",
        "best_bid": signal.best_bid,
        "best_ask": signal.best_ask,
        "spread": signal.spread,
        "avg_price": signal.avg_price,
        "shares": signal.shares,
        "amount_usd": signal.amount_usd,
        "model_probability": model_probability,
        "data_quality": signal.data_quality,
        "fixture": False,
        "payload": payload,
    }


def _position_from_signal(signal: ForwardPaperSignal) -> ForwardPaperPosition | None:
    if signal.final_action != "paper_fill" or signal.avg_price is None or signal.shares is None:
        return None
    return ForwardPaperPosition(
        position_id=f"msp_{uuid4().hex[:12]}",
        signal_id=signal.signal_id,
        run_id=signal.run_id,
        symbol=signal.symbol,
        condition_id=signal.condition_id,
        token_id=signal.token_id,
        outcome=signal.outcome,
        entry_ts_ms=signal.external_move_ts_ms,
        entry_price=signal.avg_price,
        shares=signal.shares,
        amount_usd=signal.amount_usd,
        best_bid_at_entry=signal.best_bid,
        best_ask_at_entry=signal.best_ask,
        spread_at_entry=signal.spread,
        data_quality=signal.data_quality,
    )


def run_multi_strike_paper_watch(
    *,
    db: Database,
    settings: Any,
    config: MultiStrikePaperConfig,
    run_id: str | None = None,
) -> dict[str, Any]:
    run_id = run_id or f"multi_strike_{uuid4().hex[:12]}"
    started = time.time()
    gamma = GammaClient()
    clob = ClobV2Client(settings)
    opened: list[ForwardPaperPosition] = []
    marks = 0
    try:
        events = gamma.list_events(slug=config.event_slug, active="true", closed="false", limit=5)
        if not events:
            return {"mode": "multi_strike_paper_only", "run_id": run_id, "status": "event_not_found", "event_slug": config.event_slug}
        current_price, sources, max_dev = current_reference_consensus(config.symbol)
        selected, considered = select_multi_strike_candidate(
            event=events[0],
            clob=clob,
            symbol=config.symbol,
            current_price=current_price,
            config=config,
        )
        ts_ms = int(time.time() * 1000)
        if selected is None:
            return {
                "mode": "multi_strike_paper_only",
                "run_id": run_id,
                "status": "no_candidate_opened",
                "event_slug": config.event_slug,
                "symbol": config.symbol,
                "current_price": current_price,
                "consensus_sources": list(sources),
                "max_deviation_pct": max_dev,
                "considered": considered,
            }

        entry_price = float(selected["best_ask"])
        shares = config.amount_usd / entry_price
        signal = ForwardPaperSignal(
            signal_id=f"mss_{uuid4().hex[:12]}",
            run_id=run_id,
            symbol=config.symbol,
            condition_id=selected.get("condition_id"),
            token_id=str(selected["yes_token_id"]),
            outcome="YES",
            external_move_ts_ms=ts_ms,
            amount_usd=config.amount_usd,
            final_action="paper_fill",
            data_quality="paper_live_multi_strike",
            avg_price=entry_price,
            shares=shares,
            best_bid=selected.get("best_bid"),
            best_ask=selected.get("best_ask"),
            spread=selected.get("spread"),
        )
        payload = {
            "strategy": "multi_strike_target_hit_v1",
            "event_slug": config.event_slug,
            "slug": selected.get("slug"),
            "target_price": selected.get("target_price"),
            "current_price": current_price,
            "fair_value": selected.get("fair_value"),
            "edge": selected.get("edge"),
            "quality": selected.get("quality"),
            "config": config.__dict__,
        }
        insert_forward_signal(db, _signal_row(signal, direction=str(selected["fair_value"]["direction"]), model_probability=float(selected["fair_value"]["probability_yes"]), payload=payload))
        position = _position_from_signal(signal)
        if position is None:
            return {"mode": "multi_strike_paper_only", "run_id": run_id, "status": "signal_without_position"}
        upsert_forward_position(db, position, payload=payload)
        opened.append(position)

        while time.time() - started < config.seconds and opened:
            time.sleep(min(config.mark_interval_seconds, max(0.0, config.seconds - (time.time() - started))))
            next_opened: list[ForwardPaperPosition] = []
            for position in opened:
                book = clob.get_orderbook(position.token_id)
                mark_price = book.best_bid
                if mark_price is None:
                    next_opened.append(position)
                    continue
                unrealized, mfe, mae = mark_position(position, mark_price=mark_price)
                position = update_excursions(position, mfe=mfe, mae=mae)
                marks += 1
                insert_forward_mark(
                    db,
                    position_id=position.position_id,
                    ts_ms=int(time.time() * 1000),
                    mark_price=mark_price,
                    best_bid=book.best_bid,
                    best_ask=book.best_ask,
                    unrealized_pnl=unrealized,
                    payload={"strategy": "multi_strike_target_hit_v1"},
                )
                should_exit, reason = should_exit_position(
                    position,
                    mark_price=mark_price,
                    ts_ms=int(time.time() * 1000),
                    take_profit_cents=config.take_profit_cents,
                    stop_loss_cents=config.stop_loss_cents,
                    timeout_seconds=config.timeout_seconds,
                )
                # If the theoretical edge disappears, exit at bid.
                latest_price, _, _ = current_reference_consensus(config.symbol)
                latest_fv = fair_value_target_hit(
                    current_price=latest_price,
                    target_price=float(selected["target_price"]),
                    seconds_to_expiry=float(selected["fair_value"]["seconds_to_expiry"]),
                    annualized_vol=config.annualized_vol,
                )
                latest_ask = book.best_ask
                latest_edge = latest_fv.probability_yes - latest_ask if latest_ask is not None else None
                if latest_edge is not None and latest_edge < config.exit_edge_threshold:
                    should_exit, reason = True, "edge_disappeared"
                if should_exit:
                    closed = close_position(position, ts_ms=int(time.time() * 1000), exit_price=mark_price, reason=reason)
                    upsert_forward_position(db, closed, payload={**payload, "exit_edge": latest_edge})
                else:
                    upsert_forward_position(db, position, payload=payload)
                    next_opened.append(position)
            opened = next_opened

        if config.close_open_on_end:
            for position in opened:
                book = clob.get_orderbook(position.token_id)
                if book.best_bid is not None:
                    closed = close_position(position, ts_ms=int(time.time() * 1000), exit_price=book.best_bid, reason="run_end_mark")
                    upsert_forward_position(db, closed, payload=payload)
            opened = []

        rows = db.conn.execute("SELECT * FROM forward_paper_positions WHERE run_id = ?", (run_id,)).fetchall()
        closed_rows = [dict(row) for row in rows if row["status"] == "closed"]
        open_rows = [dict(row) for row in rows if row["status"] == "open"]
        summary = {
            "mode": "multi_strike_paper_only",
            "run_id": run_id,
            "status": "completed",
            "event_slug": config.event_slug,
            "symbol": config.symbol,
            "selected": selected,
            "positions_opened": len(rows),
            "positions_open": len(open_rows),
            "positions_closed": len(closed_rows),
            "marks_written": marks,
            "net_pnl": sum(float(row["net_pnl"] or 0.0) for row in closed_rows),
            "data_quality": "paper_live_multi_strike",
        }
        insert_forward_run(
            db,
            run_id=run_id,
            symbols=(config.symbol,),
            config={**config.__dict__, "strategy": "multi_strike_target_hit_v1"},
            summary=summary,
            report={
                "positions": len(rows),
                "open": len(open_rows),
                "closed": len(closed_rows),
                "net_pnl": summary["net_pnl"],
            },
            quality={
                "warnings": ["multi_strike_model_not_calibrated"],
                "data_quality": "paper_live_multi_strike",
            },
            artifacts={},
            requested_seconds=config.seconds,
            actual_seconds=max(0, int(time.time() - started)),
            exploratory_threshold=True,
        )
        return summary
    finally:
        gamma.close()
        clob.close()
