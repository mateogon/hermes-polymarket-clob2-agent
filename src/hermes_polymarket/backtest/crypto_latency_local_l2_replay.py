"""Replay crypto latency events against locally recorded L2 books."""

from __future__ import annotations

from uuid import uuid4

from hermes_polymarket.backtest.local_l2_execution import simulate_local_l2_buy
from hermes_polymarket.storage.crypto_latency import insert_crypto_latency_opportunity
from hermes_polymarket.storage.crypto_watchlist import crypto_market_watchlist
from hermes_polymarket.storage.db import Database


def replay_crypto_latency_opportunities_local_l2(
    db: Database,
    *,
    amount_usd: float = 5.0,
    limit: int = 100,
) -> dict:
    events = [
        dict(row)
        for row in db.conn.execute(
            "SELECT * FROM crypto_latency_events ORDER BY external_move_detected_ts_ms DESC, id DESC LIMIT ?",
            (limit,),
        )
    ]
    watchlist = crypto_market_watchlist(db, active_only=True, limit=100)
    rows: list[dict] = []

    for event in events:
        for market in watchlist:
            if market["symbol"] != event["symbol"]:
                continue
            for token_id, outcome in ((market["yes_token_id"], "YES"), (market["no_token_id"], "NO")):
                local_fill = simulate_local_l2_buy(
                    db,
                    token_id=token_id,
                    target_ts_ms=int(event["external_move_detected_ts_ms"]),
                    amount_usd=amount_usd,
                )
                row = {
                    "opportunity_id": f"opp_{uuid4().hex[:12]}",
                    "event_id": event["event_id"],
                    "token_id": token_id,
                    "outcome": outcome,
                    "side": "BUY",
                    "amount_usd": amount_usd,
                    "avg_price": local_fill.fill.avg_price if local_fill.fill else None,
                    "shares": local_fill.fill.total_shares if local_fill.fill else None,
                    "fill_status": local_fill.reason,
                    "risk_allowed": False,
                    "risk_reason": "risk_not_evaluated_replay_only" if local_fill.available else "no_local_l2_fill",
                    "data_quality": "local_l2",
                    "payload": {
                        "target_ts_ms": int(event["external_move_detected_ts_ms"]),
                        "best_bid": local_fill.best_bid,
                        "best_ask": local_fill.best_ask,
                        "spread": local_fill.spread,
                        "available": local_fill.available,
                    },
                }
                insert_crypto_latency_opportunity(db, row)
                rows.append(row)

    return {
        "mode": "measurement_paper_only",
        "data_quality": "local_l2",
        "events_considered": len(events),
        "watchlist_markets": len(watchlist),
        "opportunities": len(rows),
        "rows": rows,
    }
