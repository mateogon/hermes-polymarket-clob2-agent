import asyncio

from hermes_polymarket.crypto.latency_recorder import RecorderConfig, run_crypto_latency_recorder
from hermes_polymarket.data_sources.base import DataEvent, EventType
from hermes_polymarket.data_sources.event_bus import EventBus
from hermes_polymarket.storage.crypto_latency import crypto_latency_report
from hermes_polymarket.storage.crypto_watchlist import upsert_crypto_market_watchlist
from hermes_polymarket.storage.db import Database


async def _publish_fixture(bus: EventBus) -> None:
    events = [
        ("binance", EventType.BINANCE_TRADE, "btcusdt", {"symbol": "BTCUSDT", "price": 100.0, "qty": 1}),
        ("coinbase", EventType.COINBASE_TICKER, "btc-usd", {"product_id": "BTC-USD", "price": 100.0}),
        ("binance", EventType.BINANCE_TRADE, "btcusdt", {"symbol": "BTCUSDT", "price": 101.0, "qty": 1}),
        ("coinbase", EventType.COINBASE_TICKER, "btc-usd", {"product_id": "BTC-USD", "price": 101.0}),
    ]
    ts = 1000
    for source, event_type, key, payload in events:
        await bus.publish(DataEvent(source, event_type, ts, ts, key, payload))
        ts += 1000


def test_crypto_latency_recorder_records_event(tmp_path):
    async def run():
        db = Database(tmp_path / "x.sqlite")
        db.init_schema(1000)
        bus = EventBus()
        await _publish_fixture(bus)

        summary = await run_crypto_latency_recorder(
            db=db,
            bus=bus,
            config=RecorderConfig(
                symbols=("btcusdt",),
                seconds=1,
                min_move_pct=0.5,
                cooldown_ms=0,
            ),
        )

        assert summary.events_seen == 4
        assert summary.consensus_ticks >= 2
        assert summary.latency_events >= 1
        assert summary.diagnostics["events_seen_by_source"]["binance"] == 2
        assert summary.diagnostics["threshold_hits_by_symbol"]["btcusdt"]["0.03"] >= 1
        assert crypto_latency_report(db)["events"] >= 1
        db.close()

    asyncio.run(run())


def test_crypto_latency_recorder_ignores_unconfigured_symbols(tmp_path):
    async def run():
        db = Database(tmp_path / "x.sqlite")
        db.init_schema(1000)
        bus = EventBus()
        await _publish_fixture(bus)

        summary = await run_crypto_latency_recorder(
            db=db,
            bus=bus,
            config=RecorderConfig(symbols=("ethusdt",), seconds=1, cooldown_ms=0),
        )

        assert summary.events_seen == 4
        assert summary.consensus_ticks == 0
        assert summary.latency_events == 0
        db.close()

    asyncio.run(run())


def test_crypto_watchlist_schema_available(tmp_path):
    db = Database(tmp_path / "x.sqlite")
    db.init_schema(1000)
    upsert_crypto_market_watchlist(
        db,
        {
            "condition_id": "c",
            "slug": "btc-15m",
            "question": "Bitcoin up or down in 15 minutes?",
            "symbol": "btcusdt",
            "yes_token_id": "y",
            "no_token_id": "n",
            "discovered_at_ms": 1,
        },
    )
    count = db.conn.execute("SELECT COUNT(*) AS n FROM crypto_market_watchlist").fetchone()["n"]
    assert count == 1
    db.close()
