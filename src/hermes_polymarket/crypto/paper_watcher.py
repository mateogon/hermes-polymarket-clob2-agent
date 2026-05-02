"""Forward paper watcher for crypto latency signals.

This module observes public crypto feeds and Polymarket market websocket data in
the same wall-clock window. It records paper-only opportunities; it never posts
orders.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
from time import time
from typing import Any
from uuid import uuid4

from hermes_polymarket.config import Settings, load_settings
from hermes_polymarket.crypto.directional_mapping import DirectionalToken, desired_direction_from_move, select_directional_token
from hermes_polymarket.crypto.event_adapter import price_reading_from_event
from hermes_polymarket.crypto.fair_value import evaluate_fair_value_edge
from hermes_polymarket.crypto.market_quality import MarketQualityDecision, evaluate_market_quality
from hermes_polymarket.crypto.market_score import _token_score
from hermes_polymarket.crypto.runtime_state import CryptoRuntimeState
from hermes_polymarket.crypto.stale_quote_gate import evaluate_stale_quote
from hermes_polymarket.data_sources.base import DataEvent, EventType
from hermes_polymarket.data_sources.event_bus import EventBus
from hermes_polymarket.forward_paper.calibration import ThresholdCalibration
from hermes_polymarket.forward_paper.lifecycle import (
    ForwardPaperPosition,
    close_position,
    mark_position,
    open_position_from_signal,
    should_exit_position,
    update_excursions,
)
from hermes_polymarket.forward_paper.diagnostics import shadow_risk_diagnostics
from hermes_polymarket.forward_paper.models import ForwardPaperSignal
from hermes_polymarket.polymarket.orderbook import simulate_buy_fill
from hermes_polymarket.polymarket.types import MarketMetadata, TokenInfo, TradeProposal
from hermes_polymarket.risk.exposure import ExposureSnapshot
from hermes_polymarket.risk.risk_manager import RiskManager, executable_depth_usd
from hermes_polymarket.signals.crypto_latency_detector import detect_external_move
from hermes_polymarket.signals.source_consensus import consensus_price
from hermes_polymarket.state.orderbook_state import OrderBookState
from hermes_polymarket.storage.crypto_latency import (
    insert_crypto_consensus_tick,
    insert_crypto_latency_event,
    insert_crypto_latency_opportunity,
)
from hermes_polymarket.storage.crypto_watchlist import crypto_market_watchlist, watchlist_reference
from hermes_polymarket.storage.db import Database
from hermes_polymarket.storage.forward_positions import insert_forward_mark, insert_forward_signal, upsert_forward_position
from hermes_polymarket.storage.l2 import persist_l2_event


@dataclass(frozen=True)
class PaperWatcherConfig:
    symbols: tuple[str, ...]
    seconds: int
    amount_usd: float = 5.0
    take_profit_cents: float = 8.0
    stop_loss_cents: float = 4.0
    timeout_seconds: int = 900
    model_probability: float = 0.60
    min_sources: int = 2
    max_age_ms: int = 2500
    max_deviation_pct: float = 0.25
    min_move_pct: float = 0.03
    calibration_thresholds_pct: tuple[float, ...] = (0.01, 0.02, 0.03, 0.05, 0.08)
    cooldown_ms: int = 5000
    max_events: int = 500
    fixture: bool = False
    healthy_only: bool = False
    use_stale_quote_gate: bool = False
    stale_quote_max_reprice_cents: float = 1.0
    stale_quote_window_ms: int = 1500
    use_fair_value: bool = False
    fair_value_min_edge: float = 0.03
    min_market_score: float = 0.0


@dataclass(frozen=True)
class PaperWatcherSummary:
    seconds: int
    events_seen: int
    consensus_ticks: int
    signals_generated: int
    latency_events: int
    paper_opportunities: int
    fills_simulated: int
    risk_rejected: int
    positions_opened: int
    positions_closed: int
    marks_written: int
    l2_events_seen: int
    dropped_events: int
    watchlist_markets: int
    watchlist_token_count: int
    run_id: str
    threshold_calibration: dict[str, int] = field(default_factory=dict)
    source_health: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def token_market_map(watchlist: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    for market in watchlist:
        yes_token = str(market["yes_token_id"])
        no_token = str(market["no_token_id"])
        mapping[yes_token] = {**market, "token_id": yes_token, "outcome": "YES"}
        mapping[no_token] = {**market, "token_id": no_token, "outcome": "NO"}
    return mapping


def directional_tokens(watchlist: list[dict[str, Any]]) -> list[DirectionalToken]:
    tokens: list[DirectionalToken] = []
    for market in watchlist:
        symbol = str(market.get("symbol") or "").lower()
        condition_id = str(market.get("condition_id") or "")
        up_token = market.get("up_token_id")
        down_token = market.get("down_token_id")
        if up_token:
            tokens.append(DirectionalToken(symbol, condition_id, str(up_token), "UP", "up"))
        if down_token:
            tokens.append(DirectionalToken(symbol, condition_id, str(down_token), "DOWN", "down"))
    return tokens


def _persist_signal_event(
    db: Database,
    *,
    event_id: str,
    symbol: str,
    market: dict[str, Any] | None,
    external_move_pct: float,
    detected_ts_ms: int,
    reference_price: float,
    current_price: float,
    sources: tuple[str, ...],
    run_id: str,
) -> None:
    insert_crypto_latency_event(
        db,
        {
            "event_id": event_id,
            "symbol": symbol,
            "condition_id": market.get("condition_id") if market else None,
            "external_move_pct": external_move_pct,
            "external_move_detected_ts_ms": detected_ts_ms,
            "payload": {
                "data_quality": "paper_live",
                "mode": "forward_paper_watcher",
                "run_id": run_id,
                "reference_price": reference_price,
                "current_price": current_price,
                "sources": sources,
                "slug": market.get("slug") if market else None,
            },
        },
    )


def _record_token_opportunity(
    db: Database,
    *,
    run_id: str,
    event_id: str,
    token_id: str,
    market: dict[str, Any],
    direction: str,
    book_state: OrderBookState,
    amount_usd: float,
    external_move_ts_ms: int,
    external_move_pct: float,
    model_probability: float,
    threshold_pct: float,
    source_consensus: dict[str, Any],
    settings: Settings,
    open_position_count: int,
    fixture: bool,
) -> tuple[int, int, int, ForwardPaperPosition | None]:
    state = book_state.by_token.get(token_id)
    fill = None
    book = None
    shadow_risk: dict[str, str] = {}
    depth_within_slippage_usd = None
    if state is not None:
        book = state.as_orderbook()
        fill = simulate_buy_fill(book, amount_usd, order_type="fok")

    filled = bool(fill and fill.filled)
    risk_allowed = False
    risk_reason = "no_executable_fill"
    risk_explanation = "No executable fill available"
    if filled and state is not None and fill is not None and book is not None:
        proposal = TradeProposal(
            market_id=str(market["condition_id"]),
            condition_id=str(market["condition_id"]),
            token_id=token_id,
            outcome=str(market.get("outcome") or ""),
            side="buy",
            amount_usd=amount_usd,
            model_probability=model_probability,
            confidence=0.35,
            reason="crypto forward paper signal",
        )
        metadata = MarketMetadata(
            condition_id=str(market["condition_id"]),
            min_tick_size=0.01,
            min_order_size=1.0,
            tokens=(TokenInfo(str(market["yes_token_id"]), "YES"), TokenInfo(str(market["no_token_id"]), "NO")),
        )
        if token_id not in {token.token_id for token in metadata.tokens}:
            risk_reason = "token_not_in_market"
            risk_explanation = "Token ID is not part of watchlist metadata"
        else:
            decision = RiskManager(settings).evaluate(
                proposal,
                book,
                fill,
                ExposureSnapshot(bankroll=settings.initial_bankroll, open_positions=open_position_count),
            )
            risk_allowed = decision.allowed
            risk_reason = decision.reason
            risk_explanation = decision.explanation
            depth_within_slippage_usd = executable_depth_usd(book, proposal.side, settings.max_slippage)
            shadow_risk = shadow_risk_diagnostics(
                settings=settings,
                proposal=proposal,
                book=book,
                fill=fill,
                exposure=ExposureSnapshot(bankroll=settings.initial_bankroll, open_positions=open_position_count),
            )

    midpoint = book.midpoint if book is not None else None
    slippage = fill.slippage if fill is not None else None

    row = {
        "opportunity_id": f"paper_opp_{uuid4().hex[:12]}",
        "event_id": event_id,
        "token_id": token_id,
        "outcome": str(market.get("outcome") or ""),
        "side": "BUY",
        "amount_usd": amount_usd,
        "avg_price": fill.avg_price if fill else None,
        "shares": fill.total_shares if fill else None,
        "fill_status": fill.status if fill else "no_local_book_state",
        "risk_allowed": risk_allowed,
        "risk_reason": risk_reason,
        "data_quality": "paper_live",
        "payload": {
            "mode": "forward_paper_watcher",
            "threshold_pct": threshold_pct,
            "external_move_pct": external_move_pct,
            "selected_direction": direction,
            "selected_token_id": token_id,
            "direction_mapping_source": "watchlist",
            "model_probability_raw": model_probability,
            "confidence": 0.35,
            "entry_price": fill.avg_price if fill else None,
            "condition_id": market.get("condition_id"),
            "slug": market.get("slug"),
            "symbol": market.get("symbol"),
            "direction": direction,
            "external_move_ts_ms": external_move_ts_ms,
            "best_bid": state.best_bid if state else None,
            "best_ask": state.best_ask if state else None,
            "midpoint": midpoint,
            "spread": state.spread if state else None,
            "slippage": slippage,
            "max_slippage": settings.max_slippage,
            "min_edge": settings.min_edge,
            "depth_within_slippage_usd": depth_within_slippage_usd,
            "fill_status": fill.status if fill else "no_local_book_state",
            "risk_allowed": risk_allowed,
            "risk_reason": risk_reason,
            "risk_explanation": risk_explanation,
            "source_consensus": source_consensus,
            "shadow_risk": shadow_risk,
        },
    }
    insert_crypto_latency_opportunity(db, row)
    insert_forward_signal(
        db,
        {
            "signal_id": event_id,
            "run_id": run_id,
            "symbol": str(market.get("symbol") or ""),
            "condition_id": str(market.get("condition_id") or ""),
            "token_id": token_id,
            "outcome": str(market.get("outcome") or ""),
            "direction": direction,
            "external_move_ts_ms": external_move_ts_ms,
            "external_move_pct": external_move_pct,
            "final_action": "paper_fill" if risk_allowed else "risk_rejected",
            "risk_reason": risk_reason,
            "fill_status": row["fill_status"],
            "best_bid": state.best_bid if state else None,
            "best_ask": state.best_ask if state else None,
            "spread": state.spread if state else None,
            "avg_price": fill.avg_price if fill else None,
            "shares": fill.total_shares if fill else None,
            "amount_usd": amount_usd,
            "model_probability": model_probability,
            "fixture": fixture,
            "payload": row["payload"],
        },
    )
    signal = ForwardPaperSignal(
        signal_id=event_id,
        run_id=run_id,
        symbol=str(market.get("symbol") or ""),
        condition_id=str(market.get("condition_id") or ""),
        token_id=token_id,
        outcome=str(market.get("outcome") or ""),
        external_move_ts_ms=external_move_ts_ms,
        amount_usd=amount_usd,
        final_action="paper_fill" if risk_allowed else "risk_rejected",
        avg_price=fill.avg_price if fill else None,
        shares=fill.total_shares if fill else None,
        best_bid=state.best_bid if state else None,
        best_ask=state.best_ask if state else None,
        spread=state.spread if state else None,
    )
    position = open_position_from_signal(signal)
    return 1, int(filled), int(not risk_allowed), position


def _record_market_quality_rejection(
    db: Database,
    *,
    run_id: str,
    event_id: str,
    token_id: str,
    market: dict[str, Any],
    direction: str,
    external_move_ts_ms: int,
    external_move_pct: float,
    amount_usd: float,
    model_probability: float,
    threshold_pct: float,
    source_consensus: dict[str, Any],
    quality: MarketQualityDecision,
    fixture: bool,
) -> None:
    payload = {
        "mode": "forward_paper_watcher",
        "threshold_pct": threshold_pct,
        "external_move_pct": external_move_pct,
        "selected_direction": direction,
        "selected_token_id": token_id,
        "direction_mapping_source": "watchlist",
        "model_probability_raw": model_probability,
        "confidence": 0.35,
        "condition_id": market.get("condition_id"),
        "slug": market.get("slug"),
        "symbol": market.get("symbol"),
        "direction": direction,
        "external_move_ts_ms": external_move_ts_ms,
        "risk_allowed": False,
        "risk_reason": quality.reason,
        "risk_explanation": "Market quality gate rejected this token before risk evaluation",
        "source_consensus": source_consensus,
        "market_quality": quality.to_dict(),
    }
    insert_forward_signal(
        db,
        {
            "signal_id": event_id,
            "run_id": run_id,
            "symbol": str(market.get("symbol") or ""),
            "condition_id": str(market.get("condition_id") or ""),
            "token_id": token_id,
            "outcome": str(market.get("outcome") or ""),
            "direction": direction,
            "external_move_ts_ms": external_move_ts_ms,
            "external_move_pct": external_move_pct,
            "final_action": "market_quality_rejected",
            "risk_reason": quality.reason,
            "fill_status": None,
            "best_bid": quality.best_bid,
            "best_ask": quality.best_ask,
            "spread": quality.spread,
            "avg_price": None,
            "shares": None,
            "amount_usd": amount_usd,
            "model_probability": model_probability,
            "fixture": fixture,
            "payload": payload,
        },
    )


def _record_gate_rejection(
    db: Database,
    *,
    run_id: str,
    event_id: str,
    token_id: str,
    market: dict[str, Any],
    direction: str,
    external_move_ts_ms: int,
    external_move_pct: float,
    amount_usd: float,
    model_probability: float,
    threshold_pct: float,
    source_consensus: dict[str, Any],
    final_action: str,
    reason: str,
    gate_payload: dict[str, Any],
    fixture: bool,
) -> None:
    payload = {
        "mode": "forward_paper_watcher",
        "threshold_pct": threshold_pct,
        "external_move_pct": external_move_pct,
        "selected_direction": direction,
        "selected_token_id": token_id,
        "direction_mapping_source": "watchlist",
        "model_probability_raw": model_probability,
        "condition_id": market.get("condition_id"),
        "slug": market.get("slug"),
        "symbol": market.get("symbol"),
        "direction": direction,
        "external_move_ts_ms": external_move_ts_ms,
        "risk_allowed": False,
        "risk_reason": reason,
        "source_consensus": source_consensus,
        **gate_payload,
    }
    insert_forward_signal(
        db,
        {
            "signal_id": event_id,
            "run_id": run_id,
            "symbol": str(market.get("symbol") or ""),
            "condition_id": str(market.get("condition_id") or ""),
            "token_id": token_id,
            "outcome": str(market.get("outcome") or ""),
            "direction": direction,
            "external_move_ts_ms": external_move_ts_ms,
            "external_move_pct": external_move_pct,
            "final_action": final_action,
            "risk_reason": reason,
            "fill_status": None,
            "best_bid": None,
            "best_ask": None,
            "spread": None,
            "avg_price": None,
            "shares": None,
            "amount_usd": amount_usd,
            "model_probability": model_probability,
            "fixture": fixture,
            "payload": payload,
        },
    )


def _score_current_market(book_state: OrderBookState, market: dict[str, Any]) -> dict[str, Any]:
    token_scores: list[float] = []
    reasons: set[str] = set()
    for token_id in (str(market.get("yes_token_id") or ""), str(market.get("no_token_id") or "")):
        state = book_state.by_token.get(token_id)
        if state is None:
            token_scores.append(0.0)
            reasons.add("missing_local_book_state")
            continue
        quality = evaluate_market_quality(state.as_orderbook())
        score, token_reasons = _token_score(quality.to_dict())
        token_scores.append(score)
        reasons.update(token_reasons)
    score = sum(token_scores) / len(token_scores) if token_scores else 0.0
    return {"score": round(score, 4), "reasons": sorted(reasons)}


def _mark_open_positions(
    db: Database,
    *,
    book_state: OrderBookState,
    positions: dict[str, ForwardPaperPosition],
    event: DataEvent,
    config: PaperWatcherConfig,
) -> tuple[int, int]:
    marks = 0
    closed = 0
    for position_id, position in list(positions.items()):
        if position.token_id != str(event.payload.get("asset_id") or event.key):
            continue
        state = book_state.by_token.get(position.token_id)
        if state is None or state.best_bid is None:
            continue
        mark_price = state.best_bid
        unrealized, mfe, mae = mark_position(position, mark_price=mark_price)
        marked = update_excursions(position, mfe=mfe, mae=mae)
        insert_forward_mark(
            db,
            position_id=position_id,
            ts_ms=event.received_ts_ms,
            mark_price=mark_price,
            best_bid=state.best_bid,
            best_ask=state.best_ask,
            unrealized_pnl=unrealized,
            payload={"source": "forward_paper_watcher"},
        )
        db.add_journal(
            "forward_paper_mark",
            "Marked forward paper position",
            {"position_id": position_id, "token_id": position.token_id, "mark_price": mark_price, "unrealized_pnl": unrealized},
        )
        marks += 1
        should_exit, reason = should_exit_position(
            marked,
            mark_price=mark_price,
            ts_ms=event.received_ts_ms,
            take_profit_cents=config.take_profit_cents,
            stop_loss_cents=config.stop_loss_cents,
            timeout_seconds=config.timeout_seconds,
        )
        if should_exit:
            final_position = close_position(marked, ts_ms=event.received_ts_ms, exit_price=mark_price, reason=reason)
            upsert_forward_position(db, final_position, payload={"source": "forward_paper_watcher"}, fixture=config.fixture)
            db.add_journal(
                "forward_paper_close",
                "Closed forward paper position",
                {
                    "position_id": position_id,
                    "token_id": position.token_id,
                    "exit_reason": reason,
                    "exit_price": mark_price,
                    "net_pnl": final_position.net_pnl,
                },
            )
            positions.pop(position_id, None)
            closed += 1
        else:
            positions[position_id] = marked
            upsert_forward_position(db, marked, payload={"source": "forward_paper_watcher"}, fixture=config.fixture)
    return marks, closed


async def run_crypto_paper_watcher(
    *,
    db: Database,
    bus: EventBus,
    config: PaperWatcherConfig,
    watchlist: list[dict[str, Any]] | None = None,
    runtime_state: CryptoRuntimeState | None = None,
    book_state: OrderBookState | None = None,
    settings: Settings | None = None,
) -> PaperWatcherSummary:
    settings = settings or load_settings()
    runtime_state = runtime_state or CryptoRuntimeState()
    book_state = book_state or OrderBookState()
    watchlist = watchlist if watchlist is not None else crypto_market_watchlist(db, active_only=True, limit=100)
    token_map = token_market_map(watchlist)
    directional = directional_tokens(watchlist)
    runtime_state.token_to_market.update(token_map)
    run_id = f"crypto_paper_{uuid4().hex[:12]}"
    open_positions: dict[str, ForwardPaperPosition] = {}
    calibration = ThresholdCalibration(list(config.calibration_thresholds_pct))

    started = time()
    events_seen = 0
    consensus_ticks = 0
    signals_generated = 0
    latency_events = 0
    opportunities = 0
    fills = 0
    risk_rejected = 0
    positions_opened = 0
    positions_closed = 0
    marks_written = 0
    l2_events = 0

    while time() - started < config.seconds:
        try:
            event = await asyncio.wait_for(bus.next_event(), timeout=0.5)
        except asyncio.TimeoutError:
            continue

        events_seen += 1
        db.insert_data_event(event)
        db.upsert_source_health(event, dropped_events=bus.dropped_events)

        if event.event_type in {EventType.POLY_BOOK, EventType.POLY_PRICE_CHANGE, EventType.POLY_BEST_BID_ASK, EventType.POLY_MARKET_RESOLVED}:
            book_state.apply(event)
            if event.event_type in {EventType.POLY_BOOK, EventType.POLY_PRICE_CHANGE, EventType.POLY_BEST_BID_ASK}:
                persist_l2_event(db, event)
                l2_events += 1
            marks_delta, closed_delta = _mark_open_positions(db, book_state=book_state, positions=open_positions, event=event, config=config)
            marks_written += marks_delta
            positions_closed += closed_delta

        reading = price_reading_from_event(event)
        if reading is None or reading.symbol not in config.symbols:
            continue

        runtime_state.update_reading(reading)
        current = consensus_price(
            runtime_state.readings(reading.symbol),
            now_ms=event.received_ts_ms,
            max_age_ms=config.max_age_ms,
            max_deviation_pct_allowed=config.max_deviation_pct,
            min_sources=config.min_sources,
        )
        if current is None:
            continue

        insert_crypto_consensus_tick(
            db,
            symbol=current.symbol,
            consensus_price=current.price,
            sources=current.sources,
            max_deviation_pct=current.max_deviation_pct,
            received_ts_ms=event.received_ts_ms,
        )
        consensus_ticks += 1

        previous = runtime_state.last_consensus_by_symbol.get(current.symbol)
        runtime_state.last_consensus_by_symbol[current.symbol] = current
        if previous is None:
            continue
        raw_move_pct = (current.price - previous.price) / previous.price * 100.0 if previous.price > 0 else 0.0
        calibration.observe_move(raw_move_pct)

        last_event_ts = runtime_state.last_event_ts_by_symbol.get(current.symbol, 0)
        if event.received_ts_ms - last_event_ts < config.cooldown_ms:
            continue

        signal = detect_external_move(
            symbol=current.symbol,
            previous=previous,
            current=current,
            min_move_pct=config.min_move_pct,
            detected_ts_ms=event.received_ts_ms,
        )
        if signal is None:
            continue

        runtime_state.last_event_ts_by_symbol[current.symbol] = event.received_ts_ms
        signals_generated += 1
        latency_events += 1
        selected = select_directional_token(tokens=directional, symbol=current.symbol, move_pct=signal.external_move_pct)
        market = token_map.get(selected.token_id) if selected else None
        _persist_signal_event(
            db,
            event_id=signal.event_id,
            symbol=signal.symbol,
            market=market,
            external_move_pct=signal.external_move_pct,
            detected_ts_ms=signal.detected_ts_ms,
            reference_price=signal.reference_price,
            current_price=signal.current_price,
            sources=current.sources,
            run_id=run_id,
        )

        if selected is None or market is None:
            insert_forward_signal(
                db,
                {
                    "signal_id": signal.event_id,
                    "run_id": run_id,
                    "symbol": signal.symbol,
                    "condition_id": None,
                    "token_id": None,
                    "outcome": None,
                    "direction": desired_direction_from_move(signal.external_move_pct),
                    "external_move_ts_ms": signal.detected_ts_ms,
                    "external_move_pct": signal.external_move_pct,
                    "final_action": "risk_rejected",
                    "risk_reason": "direction_mapping_missing" if not directional else "direction_mapping_ambiguous",
                    "fill_status": None,
                    "amount_usd": config.amount_usd,
                    "model_probability": config.model_probability,
                    "fixture": config.fixture,
                },
            )
            risk_rejected += 1
        else:
            state = book_state.by_token.get(selected.token_id)
            if state is None:
                quality = MarketQualityDecision(False, "no_local_book_state", None, None, None, 0.0, 0.0)
            else:
                quality = evaluate_market_quality(state.as_orderbook())
            if not quality.allowed:
                _record_market_quality_rejection(
                    db,
                    run_id=run_id,
                    event_id=signal.event_id,
                    token_id=selected.token_id,
                    market=market,
                    direction=selected.direction,
                    external_move_ts_ms=signal.detected_ts_ms,
                    external_move_pct=signal.external_move_pct,
                    amount_usd=config.amount_usd,
                    model_probability=config.model_probability,
                    threshold_pct=config.min_move_pct,
                    source_consensus={"sources": list(current.sources), "max_deviation_pct": current.max_deviation_pct},
                    quality=quality,
                    fixture=config.fixture,
                )
                risk_rejected += 1
                continue
            if config.min_market_score > 0:
                market_score = _score_current_market(book_state, market)
                if float(market_score["score"]) < config.min_market_score:
                    _record_gate_rejection(
                        db,
                        run_id=run_id,
                        event_id=signal.event_id,
                        token_id=selected.token_id,
                        market=market,
                        direction=selected.direction,
                        external_move_ts_ms=signal.detected_ts_ms,
                        external_move_pct=signal.external_move_pct,
                        amount_usd=config.amount_usd,
                        model_probability=config.model_probability,
                        threshold_pct=config.min_move_pct,
                        source_consensus={"sources": list(current.sources), "max_deviation_pct": current.max_deviation_pct},
                        final_action="market_score_rejected",
                        reason="market_score_below_threshold",
                        gate_payload={"market_score": {**market_score, "min_required": config.min_market_score}},
                        fixture=config.fixture,
                    )
                    risk_rejected += 1
                    continue
            if config.use_stale_quote_gate:
                current_bbo = {"best_bid": quality.best_bid, "best_ask": quality.best_ask}
                stale = evaluate_stale_quote(
                    external_move_pct=signal.external_move_pct,
                    bbo_before=current_bbo,
                    bbo_after=current_bbo,
                    max_reprice_cents=config.stale_quote_max_reprice_cents,
                    stale_window_ms=config.stale_quote_window_ms,
                    require_bbo_before=True,
                    require_bbo_after=True,
                )
                if not stale.allowed:
                    _record_gate_rejection(
                        db,
                        run_id=run_id,
                        event_id=signal.event_id,
                        token_id=selected.token_id,
                        market=market,
                        direction=selected.direction,
                        external_move_ts_ms=signal.detected_ts_ms,
                        external_move_pct=signal.external_move_pct,
                        amount_usd=config.amount_usd,
                        model_probability=config.model_probability,
                        threshold_pct=config.min_move_pct,
                        source_consensus={"sources": list(current.sources), "max_deviation_pct": current.max_deviation_pct},
                        final_action="stale_quote_rejected",
                        reason=stale.reason,
                        gate_payload={"stale_quote": stale.to_dict()},
                        fixture=config.fixture,
                    )
                    risk_rejected += 1
                    continue
            if config.use_fair_value:
                ref = watchlist_reference(market)
                reference_price = ref.get("reference_price")
                window_end_ts = ref.get("window_end_ts")
                if reference_price is None or window_end_ts is None or quality.best_ask is None:
                    reason = "reference_price_missing"
                    payload = {"fair_value": {"allowed": False, "reason": reason, "reference": ref}}
                else:
                    seconds_to_expiry = max(1.0, float(window_end_ts) - signal.detected_ts_ms / 1000.0)
                    fair = evaluate_fair_value_edge(
                        direction=selected.direction,
                        current_price=signal.current_price,
                        reference_price=float(reference_price),
                        seconds_to_expiry=seconds_to_expiry,
                        executable_price=float(quality.best_ask),
                        min_edge=config.fair_value_min_edge,
                    )
                    reason = fair.reason
                    payload = {"fair_value": fair.to_dict()}
                if reason != "fair_value_edge":
                    _record_gate_rejection(
                        db,
                        run_id=run_id,
                        event_id=signal.event_id,
                        token_id=selected.token_id,
                        market=market,
                        direction=selected.direction,
                        external_move_ts_ms=signal.detected_ts_ms,
                        external_move_pct=signal.external_move_pct,
                        amount_usd=config.amount_usd,
                        model_probability=config.model_probability,
                        threshold_pct=config.min_move_pct,
                        source_consensus={"sources": list(current.sources), "max_deviation_pct": current.max_deviation_pct},
                        final_action="fair_value_rejected",
                        reason=reason,
                        gate_payload=payload,
                        fixture=config.fixture,
                    )
                    risk_rejected += 1
                    continue
            opp_delta, fill_delta, reject_delta, position = _record_token_opportunity(
                db,
                run_id=run_id,
                event_id=signal.event_id,
                token_id=selected.token_id,
                market=market,
                direction=selected.direction,
                book_state=book_state,
                amount_usd=config.amount_usd,
                external_move_ts_ms=signal.detected_ts_ms,
                external_move_pct=signal.external_move_pct,
                model_probability=config.model_probability,
                settings=settings,
                threshold_pct=config.min_move_pct,
                source_consensus={"sources": list(current.sources), "max_deviation_pct": current.max_deviation_pct},
                open_position_count=len(open_positions),
                fixture=config.fixture,
            )
            opportunities += opp_delta
            fills += fill_delta
            risk_rejected += reject_delta
            if position is not None:
                open_positions[position.position_id] = position
                upsert_forward_position(db, position, payload={"source": "forward_paper_watcher"}, fixture=config.fixture)
                db.add_journal(
                    "forward_paper_open",
                    "Opened forward paper position",
                    {
                        "position_id": position.position_id,
                        "signal_id": position.signal_id,
                        "token_id": position.token_id,
                        "entry_price": position.entry_price,
                        "shares": position.shares,
                    },
                )
                positions_opened += 1

        if latency_events >= config.max_events:
            break

    return PaperWatcherSummary(
        seconds=config.seconds,
        events_seen=events_seen,
        consensus_ticks=consensus_ticks,
        signals_generated=signals_generated,
        latency_events=latency_events,
        paper_opportunities=opportunities,
        fills_simulated=fills,
        risk_rejected=risk_rejected,
        positions_opened=positions_opened,
        positions_closed=positions_closed,
        marks_written=marks_written,
        l2_events_seen=l2_events,
        dropped_events=bus.dropped_events,
        watchlist_markets=len(watchlist),
        watchlist_token_count=len(token_map),
        run_id=run_id,
        threshold_calibration=calibration.to_dict(),
        source_health=[dict(row) for row in db.source_health()],
    )
