"""Multi-strike target-hit paper watcher.

This is research-only. It uses public Gamma/CLOB REST data and writes paper
signals/positions; it never places orders.
"""

from __future__ import annotations

import contextlib
import atexit
from dataclasses import dataclass
from datetime import datetime, timezone
import faulthandler
import json
import os
import signal
import sys
import time
import traceback
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


class MultiStrikePaperShutdown(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


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
    max_sleep_seconds: int = 5


class _RunEventLogger:
    def __init__(self, *, run_id: str) -> None:
        self.run_id = run_id
        self.path = os.getenv("HERMES_RUN_EVENT_LOG_PATH")
        self._handle = None
        self._atexit_registered = False
        if self.path:
            os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
            self._handle = open(self.path, "a", buffering=1)
            with contextlib.suppress(Exception):
                faulthandler.enable(file=self._handle)

    def log(self, event: str, **fields: Any) -> None:
        row = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "pid": os.getpid(),
            "run_id": self.run_id,
            "event": event,
            **fields,
        }
        text = json.dumps(row, sort_keys=True, default=str)
        print(text, file=sys.stderr, flush=True)
        if self._handle is not None:
            with contextlib.suppress(Exception):
                self._handle.write(text + "\n")
                self._handle.flush()

    def register_atexit(self) -> None:
        if self._atexit_registered:
            return
        self._atexit_registered = True
        atexit.register(lambda: self.log("process_atexit"))

    def close(self) -> None:
        if self._handle is not None:
            with contextlib.suppress(Exception):
                faulthandler.disable()
                self._handle.flush()
                self._handle.close()
            self._handle = None


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
    log_event: Any | None = None,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    universe = scan_market_universe(events=[event], markets=[], symbols={symbol})
    considered: list[dict[str, Any]] = []
    rows = filter_universe_candidates(universe, market_type="multi_strike_event", min_score=0.0, limit=500)
    if log_event is not None:
        log_event("candidate_rows_built", rows=len(rows), classified=universe.get("classified"))
    for index, row in enumerate(rows, start=1):
        if not row.get("active") or row.get("closed"):
            if log_event is not None:
                log_event("candidate_skip_inactive", index=index, slug=row.get("slug"), active=row.get("active"), closed=row.get("closed"))
            continue
        token_id = row.get("yes_token_id")
        if not token_id:
            if log_event is not None:
                log_event("candidate_rejected", index=index, slug=row.get("slug"), reason="missing_yes_token_id")
            considered.append({**row, "selected": False, "reject_reason": "missing_yes_token_id"})
            continue
        try:
            if log_event is not None:
                log_event("candidate_book_fetch_start", index=index, slug=row.get("slug"), token_id=token_id)
            book = clob.get_orderbook(str(token_id))
            if log_event is not None:
                log_event(
                    "candidate_book_fetch_done",
                    index=index,
                    slug=row.get("slug"),
                    token_id=token_id,
                    best_bid=book.best_bid,
                    best_ask=book.best_ask,
                    spread=book.spread,
                )
            if log_event is not None:
                log_event("candidate_payload_start", index=index, slug=row.get("slug"))
            candidate = _candidate_payload(row=row, book=book, current_price=current_price, annualized_vol=config.annualized_vol)
            if log_event is not None:
                log_event(
                    "candidate_payload_done",
                    index=index,
                    slug=row.get("slug"),
                    target_price=candidate.get("target_price") if candidate else None,
                    edge=candidate.get("edge") if candidate else None,
                )
        except Exception as exc:  # noqa: BLE001 - research CLI reports per-market failures.
            if log_event is not None:
                log_event("candidate_book_error", index=index, slug=row.get("slug"), token_id=token_id, error_type=type(exc).__name__, error=str(exc))
            considered.append({**row, "selected": False, "reject_reason": f"book_error:{exc}"})
            continue
        if candidate is None:
            if log_event is not None:
                log_event("candidate_rejected", index=index, slug=row.get("slug"), reason="target_parse_failed")
            considered.append({**row, "selected": False, "reject_reason": "target_parse_failed"})
            continue
        reasons: list[str] = []
        if not candidate["quality"].get("allowed"):
            reasons.append(f"quality:{candidate['quality'].get('reason')}")
        best_bid = candidate.get("best_bid")
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
        elif spread > config.max_spread + 1e-9:
            reasons.append("spread_above_max")
        if edge is not None and spread is not None and edge < spread + config.edge_spread_buffer:
            reasons.append("edge_below_spread_buffer")
        if log_event is not None:
            log_event(
                "candidate_evaluated",
                index=index,
                slug=row.get("slug"),
                selected=not reasons,
                reject_reason=",".join(reasons) if reasons else "ok",
                best_bid=best_bid,
                best_ask=best_ask,
                spread=spread,
                edge=edge,
            )
        considered.append({**candidate, "selected": not reasons, "reject_reason": ",".join(reasons) if reasons else "ok"})

    selected = [row for row in considered if row.get("selected")]
    selected.sort(key=lambda row: float(row.get("edge") or -999.0), reverse=True)
    if log_event is not None:
        log_event("candidate_selection_sorted", selected=len(selected), considered=len(considered), selected_slug=selected[0].get("slug") if selected else None)
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
    events_log = _RunEventLogger(run_id=run_id)
    events_log.register_atexit()
    events_log.log(
        "process_start",
        cwd=os.getcwd(),
        database_path=str(getattr(settings, "database_path", "")),
        event_log_path=events_log.path,
        config=config.__dict__,
    )
    gamma = GammaClient()
    clob = ClobV2Client(settings)
    opened: list[ForwardPaperPosition] = []
    active_payload: dict[str, Any] = {}
    active_selected: dict[str, Any] | None = None
    marks = 0
    stop_requested: str | None = None
    previous_handlers: dict[int, Any] = {}

    def _request_stop(signum: int, _frame: Any) -> None:
        nonlocal stop_requested
        stop_requested = signal.Signals(signum).name.lower()
        events_log.log("shutdown_signal", signal=stop_requested)
        raise MultiStrikePaperShutdown(stop_requested)

    for signum in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(ValueError):
            previous_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, _request_stop)
            events_log.log("signal_handler_installed", signal=signal.Signals(signum).name.lower())

    def _insert_run(summary: dict[str, Any], *, warnings: list[str] | None = None) -> None:
        events_log.log("run_persist_start", status=summary.get("status"), warnings=warnings or [])
        rows = db.conn.execute("SELECT * FROM forward_paper_positions WHERE run_id = ?", (run_id,)).fetchall()
        closed_rows = [dict(row) for row in rows if row["status"] == "closed"]
        open_rows = [dict(row) for row in rows if row["status"] == "open"]
        insert_forward_run(
            db,
            run_id=run_id,
            symbols=(config.symbol,),
            config={**config.__dict__, "strategy": "multi_strike_target_hit_v1"},
            summary={**summary, "positions_opened": len(rows), "positions_open": len(open_rows), "positions_closed": len(closed_rows)},
            report={
                "positions": len(rows),
                "open": len(open_rows),
                "closed": len(closed_rows),
                "net_pnl": sum(float(row["net_pnl"] or 0.0) for row in closed_rows),
            },
            quality={
                "warnings": warnings or ["multi_strike_model_not_calibrated"],
                "data_quality": "paper_live_multi_strike",
            },
            artifacts={},
            requested_seconds=config.seconds,
            actual_seconds=max(0, int(time.time() - started)),
            exploratory_threshold=True,
        )
        events_log.log(
            "run_persist_done",
            status=summary.get("status"),
            positions=len(rows),
            open=len(open_rows),
            closed=len(closed_rows),
        )

    def _mark_open_position(position: ForwardPaperPosition, *, payload: dict[str, Any], reason_payload: dict[str, Any] | None = None) -> tuple[ForwardPaperPosition, float | None, OrderBook]:
        events_log.log("mark_start", position_id=position.position_id, token_id=position.token_id, reason=(reason_payload or {}).get("reason"))
        book = clob.get_orderbook(position.token_id)
        mark_price = book.best_bid
        if mark_price is None:
            events_log.log(
                "mark_no_best_bid",
                position_id=position.position_id,
                best_bid=book.best_bid,
                best_ask=book.best_ask,
            )
            return position, None, book
        unrealized, mfe, mae = mark_position(position, mark_price=mark_price)
        position = update_excursions(position, mfe=mfe, mae=mae)
        insert_forward_mark(
            db,
            position_id=position.position_id,
            ts_ms=int(time.time() * 1000),
            mark_price=mark_price,
            best_bid=book.best_bid,
            best_ask=book.best_ask,
            unrealized_pnl=unrealized,
            payload={"strategy": "multi_strike_target_hit_v1", **(reason_payload or {})},
        )
        upsert_forward_position(db, position, payload=payload)
        events_log.log(
            "mark_done",
            position_id=position.position_id,
            mark_price=mark_price,
            best_bid=book.best_bid,
            best_ask=book.best_ask,
            unrealized_pnl=unrealized,
            mfe=mfe,
            mae=mae,
        )
        return position, mark_price, book

    try:
        events_log.log("events_fetch_start", event_slug=config.event_slug)
        events = gamma.list_events(slug=config.event_slug, active="true", closed="false", limit=5)
        events_log.log("events_fetch_done", events=len(events))
        if not events:
            _insert_run(
                {
                    "mode": "multi_strike_paper_only",
                    "run_id": run_id,
                    "status": "event_not_found",
                    "event_slug": config.event_slug,
                    "symbol": config.symbol,
                    "data_quality": "paper_live_multi_strike",
                    "marks_written": marks,
                    "net_pnl": 0.0,
                },
                warnings=["multi_strike_model_not_calibrated", "event_not_found"],
            )
            events_log.log("event_not_found", event_slug=config.event_slug)
            return {"mode": "multi_strike_paper_only", "run_id": run_id, "status": "event_not_found", "event_slug": config.event_slug}
        events_log.log("consensus_fetch_start", symbol=config.symbol)
        current_price, sources, max_dev = current_reference_consensus(config.symbol)
        events_log.log("consensus_fetch_done", symbol=config.symbol, current_price=current_price, sources=list(sources), max_deviation_pct=max_dev)
        events_log.log("candidate_select_start", event_slug=config.event_slug, symbol=config.symbol, current_price=current_price)
        selected, considered = select_multi_strike_candidate(
            event=events[0],
            clob=clob,
            symbol=config.symbol,
            current_price=current_price,
            config=config,
            log_event=events_log.log,
        )
        events_log.log("candidate_select_done", considered=len(considered), selected_slug=selected.get("slug") if selected else None)
        ts_ms = int(time.time() * 1000)
        if selected is None:
            reject_counts: dict[str, int] = {}
            for row in considered:
                reason = str(row.get("reject_reason") or "unknown")
                reject_counts[reason] = reject_counts.get(reason, 0) + 1
            _insert_run(
                {
                    "mode": "multi_strike_paper_only",
                    "run_id": run_id,
                    "status": "no_candidate_opened",
                    "event_slug": config.event_slug,
                    "symbol": config.symbol,
                    "current_price": current_price,
                    "max_deviation_pct": max_dev,
                    "considered_count": len(considered),
                    "reject_counts": reject_counts,
                    "data_quality": "paper_live_multi_strike",
                    "marks_written": marks,
                    "net_pnl": 0.0,
                },
                warnings=["multi_strike_model_not_calibrated", "no_candidate_opened"],
            )
            events_log.log("no_candidate_opened", reject_counts=reject_counts)
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
        paper_signal = ForwardPaperSignal(
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
        active_payload = payload
        active_selected = selected
        events_log.log(
            "signal_persist_start",
            signal_id=paper_signal.signal_id,
            token_id=paper_signal.token_id,
            entry_price=entry_price,
            shares=shares,
            edge=selected.get("edge"),
        )
        insert_forward_signal(db, _signal_row(paper_signal, direction=str(selected["fair_value"]["direction"]), model_probability=float(selected["fair_value"]["probability_yes"]), payload=payload))
        events_log.log("signal_persist_done", signal_id=paper_signal.signal_id)
        position = _position_from_signal(paper_signal)
        if position is None:
            events_log.log("signal_without_position", signal_id=paper_signal.signal_id)
            return {"mode": "multi_strike_paper_only", "run_id": run_id, "status": "signal_without_position"}
        events_log.log("position_open_start", position_id=position.position_id)
        upsert_forward_position(db, position, payload=payload)
        opened.append(position)
        events_log.log("position_opened", position_id=position.position_id, token_id=position.token_id, entry_price=position.entry_price, shares=position.shares)
        _insert_run(
            {
                "mode": "multi_strike_paper_only",
                "run_id": run_id,
                "status": "opened",
                "event_slug": config.event_slug,
                "symbol": config.symbol,
                "data_quality": "paper_live_multi_strike",
                "marks_written": marks,
                "net_pnl": 0.0,
            },
            warnings=["multi_strike_model_not_calibrated", "run_in_progress"],
        )
        position, mark_price, _ = _mark_open_position(position, payload=payload, reason_payload={"reason": "entry_mark"})
        if mark_price is not None:
            marks += 1
            opened = [position]
            events_log.log("entry_mark_done", marks_written=marks, mark_price=mark_price)

        next_mark_at = time.time() + max(0, config.mark_interval_seconds)
        while time.time() - started < config.seconds and opened and stop_requested is None:
            sleep_for = min(
                max(0.0, next_mark_at - time.time()),
                max(1, config.max_sleep_seconds),
                max(0.0, config.seconds - (time.time() - started)),
            )
            if sleep_for > 0:
                events_log.log(
                    "sleep_start",
                    sleep_seconds=sleep_for,
                    elapsed_seconds=time.time() - started,
                    next_mark_in_seconds=max(0.0, next_mark_at - time.time()),
                    open_positions=len(opened),
                    marks_written=marks,
                )
                time.sleep(sleep_for)
                events_log.log("sleep_done", elapsed_seconds=time.time() - started, open_positions=len(opened), marks_written=marks)
            if time.time() < next_mark_at and time.time() - started < config.seconds and stop_requested is None:
                continue
            next_mark_at = time.time() + max(0, config.mark_interval_seconds)
            next_opened: list[ForwardPaperPosition] = []
            for position in opened:
                position, mark_price, book = _mark_open_position(position, payload=payload)
                if mark_price is None:
                    next_opened.append(position)
                    continue
                marks += 1
                events_log.log("exit_check_start", position_id=position.position_id, mark_price=mark_price)
                should_exit, reason = should_exit_position(
                    position,
                    mark_price=mark_price,
                    ts_ms=int(time.time() * 1000),
                    take_profit_cents=config.take_profit_cents,
                    stop_loss_cents=config.stop_loss_cents,
                    timeout_seconds=config.timeout_seconds,
                )
                # If the theoretical edge disappears, exit at bid.
                events_log.log("latest_consensus_fetch_start", symbol=config.symbol)
                latest_price, _, _ = current_reference_consensus(config.symbol)
                events_log.log("latest_consensus_fetch_done", symbol=config.symbol, latest_price=latest_price)
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
                events_log.log(
                    "exit_check_done",
                    position_id=position.position_id,
                    should_exit=should_exit,
                    reason=reason,
                    latest_edge=latest_edge,
                    latest_ask=latest_ask,
                )
                if should_exit:
                    closed = close_position(position, ts_ms=int(time.time() * 1000), exit_price=mark_price, reason=reason)
                    events_log.log("position_close_start", position_id=position.position_id, reason=reason, exit_price=mark_price)
                    upsert_forward_position(db, closed, payload={**payload, "exit_edge": latest_edge})
                    events_log.log("position_closed", position_id=position.position_id, reason=reason, net_pnl=closed.net_pnl)
                else:
                    next_opened.append(position)
            opened = next_opened

        if config.close_open_on_end or stop_requested is not None:
            events_log.log("close_open_on_end_start", open_positions=len(opened), stop_requested=stop_requested)
            for position in opened:
                events_log.log("run_end_book_fetch_start", position_id=position.position_id, token_id=position.token_id)
                book = clob.get_orderbook(position.token_id)
                events_log.log("run_end_book_fetch_done", position_id=position.position_id, best_bid=book.best_bid, best_ask=book.best_ask)
                if book.best_bid is not None:
                    reason = f"interrupted_{stop_requested}" if stop_requested is not None else "run_end_mark"
                    closed = close_position(position, ts_ms=int(time.time() * 1000), exit_price=book.best_bid, reason=reason)
                    events_log.log("run_end_position_close_start", position_id=position.position_id, reason=reason, exit_price=book.best_bid)
                    upsert_forward_position(db, closed, payload={**payload, "interrupted_by": stop_requested})
                    events_log.log("run_end_position_closed", position_id=position.position_id, reason=reason, net_pnl=closed.net_pnl)
            opened = []
            events_log.log("close_open_on_end_done")

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
        if stop_requested is not None:
            summary["status"] = "interrupted"
            summary["interrupted_by"] = stop_requested
        _insert_run(summary, warnings=["multi_strike_model_not_calibrated"] + ([f"interrupted_by_{stop_requested}"] if stop_requested else []))
        events_log.log("run_completed_persisted", status=summary["status"], marks_written=marks, net_pnl=summary["net_pnl"])
        return summary
    except MultiStrikePaperShutdown as exc:
        stop_requested = exc.reason
        events_log.log("shutdown_exception", reason=stop_requested)
        if opened:
            for position in opened:
                with contextlib.suppress(Exception):
                    events_log.log("shutdown_book_fetch_start", position_id=position.position_id, token_id=position.token_id)
                    book = clob.get_orderbook(position.token_id)
                    events_log.log("shutdown_book_fetch_done", position_id=position.position_id, best_bid=book.best_bid, best_ask=book.best_ask)
                    if book.best_bid is not None:
                        closed = close_position(position, ts_ms=int(time.time() * 1000), exit_price=book.best_bid, reason=f"interrupted_{stop_requested}")
                        events_log.log("shutdown_position_close_start", position_id=position.position_id, exit_price=book.best_bid)
                        upsert_forward_position(db, closed, payload={**active_payload, "interrupted_by": stop_requested})
                        events_log.log("shutdown_position_closed", position_id=position.position_id, net_pnl=closed.net_pnl)
            opened = []
        rows = db.conn.execute("SELECT * FROM forward_paper_positions WHERE run_id = ?", (run_id,)).fetchall()
        closed_rows = [dict(row) for row in rows if row["status"] == "closed"]
        open_rows = [dict(row) for row in rows if row["status"] == "open"]
        summary = {
            "mode": "multi_strike_paper_only",
            "run_id": run_id,
            "status": "interrupted",
            "interrupted_by": stop_requested,
            "event_slug": config.event_slug,
            "symbol": config.symbol,
            "selected": active_selected,
            "positions_opened": len(rows),
            "positions_open": len(open_rows),
            "positions_closed": len(closed_rows),
            "marks_written": marks,
            "net_pnl": sum(float(row["net_pnl"] or 0.0) for row in closed_rows),
            "data_quality": "paper_live_multi_strike",
        }
        _insert_run(summary, warnings=["multi_strike_model_not_calibrated", f"interrupted_by_{stop_requested}"])
        events_log.log("shutdown_persisted", reason=stop_requested, closed=len(closed_rows), open=len(open_rows), marks_written=marks)
        return summary
    except BaseException as exc:
        events_log.log("exception", error_type=type(exc).__name__, error=str(exc), traceback=traceback.format_exc())
        _insert_run(
            {
                "mode": "multi_strike_paper_only",
                "run_id": run_id,
                "status": "error",
                "event_slug": config.event_slug,
                "symbol": config.symbol,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "marks_written": marks,
                "net_pnl": 0.0,
                "data_quality": "paper_live_multi_strike",
            },
            warnings=["multi_strike_model_not_calibrated", "run_error"],
        )
        raise
    finally:
        events_log.log("finally_start")
        for signum, handler in previous_handlers.items():
            with contextlib.suppress(ValueError):
                signal.signal(signum, handler)
                events_log.log("signal_handler_restored", signal=signal.Signals(signum).name.lower())
        events_log.log("clients_close_start")
        gamma.close()
        clob.close()
        events_log.log("clients_close_done")
        events_log.close()
