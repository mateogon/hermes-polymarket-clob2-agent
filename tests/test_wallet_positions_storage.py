from hermes_polymarket.data_sources.polymarket_positions_api import ClosedPosition, CurrentPosition
from hermes_polymarket.storage.db import Database
from hermes_polymarket.storage.wallet_positions import (
    closed_positions,
    current_positions,
    insert_closed_positions,
    upsert_current_positions,
)


WALLET = "0x55be7aa03ecfbe37aa5460db791205f7ac9ddca3"


def current_pos(size=10):
    return CurrentPosition(
        wallet=WALLET,
        asset_id="asset",
        condition_id="condition",
        size=size,
        avg_price=0.4,
        initial_value=4,
        current_value=5,
        cash_pnl=1,
        percent_pnl=25,
        total_bought=100,
        realized_pnl=0,
        cur_price=0.5,
        redeemable=False,
        mergeable=False,
        title="title",
        slug="slug",
        event_slug="event",
        outcome="Yes",
        outcome_index=0,
        opposite_outcome="No",
        opposite_asset="other",
        end_date="2026-01-01",
        negative_risk=False,
        raw={},
    )


def closed_pos():
    return ClosedPosition(
        wallet=WALLET,
        asset_id="asset",
        condition_id="condition",
        avg_price=0.4,
        total_bought=100,
        realized_pnl=12.5,
        cur_price=1,
        timestamp=123,
        title="title",
        slug="slug",
        event_slug="event",
        outcome="Yes",
        outcome_index=0,
        opposite_outcome="No",
        opposite_asset="other",
        end_date="2026-01-01",
        raw={},
    )


def test_wallet_position_storage_roundtrip(tmp_path):
    db = Database(tmp_path / "positions.sqlite3")
    db.init_schema(1000)
    assert upsert_current_positions(db, [current_pos(), current_pos(size=12)]) == 2
    assert current_positions(db, WALLET)[0]["size"] == 12
    counts = insert_closed_positions(db, [closed_pos(), closed_pos()])
    assert counts == {"fetched": 2, "inserted": 1, "duplicates": 1}
    assert closed_positions(db, WALLET)[0]["realized_pnl"] == 12.5
    db.close()
