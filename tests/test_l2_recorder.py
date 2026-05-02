import asyncio

from hermes_polymarket.crypto.l2_recorder import run_l2_recorder
from hermes_polymarket.data_sources.base import DataEvent, EventType
from hermes_polymarket.data_sources.event_bus import EventBus
from hermes_polymarket.storage.db import Database


def test_l2_recorder_persists_fixture_events(tmp_path):
    async def run():
        db = Database(tmp_path / "x.sqlite")
        db.init_schema(1000)
        bus = EventBus()
        await bus.publish(
            DataEvent(
                "fixture",
                EventType.POLY_BEST_BID_ASK,
                None,
                1000,
                "token",
                {"bid": "0.49", "ask": "0.51"},
            )
        )

        summary = await run_l2_recorder(db=db, bus=bus, token_ids=("token",), seconds=1)

        assert summary.bbo_seen == 1
        assert db.conn.execute("SELECT COUNT(*) AS n FROM l2_bbo_updates").fetchone()["n"] == 1
        db.close()

    asyncio.run(run())
