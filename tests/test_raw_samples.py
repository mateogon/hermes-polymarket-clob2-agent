from hermes_polymarket.data_sources.base import DataEvent, EventType
from hermes_polymarket.storage.db import Database
from hermes_polymarket.storage.raw_samples import insert_raw_sample, raw_samples


def test_raw_samples_roundtrip(tmp_path):
    db = Database(tmp_path / "x.sqlite")
    db.init_schema(1000)
    event = DataEvent(
        source="polymarket_rtds",
        event_type=EventType.SOURCE_HEALTH,
        event_ts_ms=None,
        received_ts_ms=123,
        key="connected",
        payload={"ok": True},
    )

    insert_raw_sample(db, event)
    rows = raw_samples(db, source="polymarket_rtds")

    assert len(rows) == 1
    assert rows[0]["event_key"] == "connected"
    db.close()
