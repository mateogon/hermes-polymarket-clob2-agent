import asyncio
import json

from hermes_polymarket.crypto.paper_watcher import PaperWatcherConfig, run_crypto_paper_watcher
from hermes_polymarket.data_sources.base import DataEvent, EventType
from hermes_polymarket.data_sources.event_bus import EventBus
from hermes_polymarket.storage.crypto_latency import crypto_latency_opportunities
from hermes_polymarket.storage.crypto_watchlist import upsert_crypto_market_watchlist
from hermes_polymarket.storage.db import Database
from hermes_polymarket.storage.forward_positions import forward_signals


async def _publish_fixture(bus: EventBus) -> None:
    await bus.publish(
        DataEvent(
            "fixture_market_ws",
            EventType.POLY_BOOK,
            1000,
            1000,
            "yes-token",
            {
                "asset_id": "yes-token",
                "market": "condition",
                "bids": [{"price": "0.49", "size": "100"}],
                "asks": [{"price": "0.50", "size": "100"}],
            },
        )
    )
    events = [
        ("fixture_binance", EventType.BINANCE_TRADE, "ethusdt", {"symbol": "ETHUSDT", "price": 100.0}),
        ("fixture_coinbase", EventType.COINBASE_TICKER, "eth-usd", {"product_id": "ETH-USD", "price": 100.0}),
        ("fixture_binance", EventType.BINANCE_TRADE, "ethusdt", {"symbol": "ETHUSDT", "price": 101.0}),
        ("fixture_coinbase", EventType.COINBASE_TICKER, "eth-usd", {"product_id": "ETH-USD", "price": 101.0}),
    ]
    ts = 1100
    for source, event_type, key, payload in events:
        await bus.publish(DataEvent(source, event_type, ts, ts, key, payload))
        ts += 1000
    await bus.publish(
        DataEvent(
            "fixture_market_ws",
            EventType.POLY_BEST_BID_ASK,
            ts,
            ts,
            "yes-token",
            {"asset_id": "yes-token", "market": "condition", "best_bid": "0.60", "best_ask": "0.61"},
        )
    )


def test_crypto_paper_watcher_records_paper_opportunity(tmp_path):
    async def run():
        db = Database(tmp_path / "x.sqlite")
        db.init_schema(1000)
        upsert_crypto_market_watchlist(
            db,
            {
                "condition_id": "condition",
                "slug": "eth-test",
                "symbol": "ethusdt",
                "yes_token_id": "yes-token",
                "no_token_id": "no-token",
                "up_token_id": "yes-token",
                "down_token_id": "no-token",
                "direction_map": {"up": "yes-token", "down": "no-token"},
                "active": True,
                "discovered_at_ms": 1,
            },
        )
        bus = EventBus()
        await _publish_fixture(bus)

        summary = await run_crypto_paper_watcher(
            db=db,
            bus=bus,
            config=PaperWatcherConfig(
                symbols=("ethusdt",),
                seconds=1,
                min_move_pct=0.5,
                cooldown_ms=0,
            ),
        )

        assert summary.signals_generated >= 1
        assert summary.paper_opportunities >= 1
        assert summary.fills_simulated >= 1
        assert summary.positions_opened == 1
        assert summary.positions_closed == 1
        assert summary.marks_written >= 1
        rows = crypto_latency_opportunities(db, limit=10)
        assert rows
        assert rows[0]["data_quality"] == "paper_live"
        signals = forward_signals(db, run_id=summary.run_id, limit=10)
        assert signals
        payload = json.loads(signals[0]["payload_json"])
        assert payload["threshold_pct"] == 0.5
        assert "slippage" in payload
        assert "shadow_risk" in payload

    asyncio.run(run())
