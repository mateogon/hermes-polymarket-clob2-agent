from hermes_polymarket.storage.crypto_latency import (
    crypto_latency_opportunities,
    crypto_latency_report,
    insert_crypto_consensus_tick,
    insert_crypto_latency_event,
    insert_crypto_latency_opportunity,
    insert_crypto_market_window,
)
from hermes_polymarket.storage.db import Database


def test_crypto_latency_report_empty(tmp_path):
    db = Database(tmp_path / "x.sqlite")
    db.init_schema(1000)
    assert crypto_latency_report(db)["events"] == 0
    db.close()


def test_insert_crypto_latency_records(tmp_path):
    db = Database(tmp_path / "x.sqlite")
    db.init_schema(1000)
    insert_crypto_market_window(
        db,
        {
            "condition_id": "c",
            "slug": "btc-up",
            "symbol": "btcusdt",
            "yes_token_id": "yes",
            "no_token_id": "no",
        },
    )
    insert_crypto_consensus_tick(db, symbol="btcusdt", consensus_price=100, sources=("binance", "coinbase"), max_deviation_pct=0.01, received_ts_ms=123)
    insert_crypto_latency_event(
        db,
        {
            "event_id": "e1",
            "symbol": "btcusdt",
            "external_move_pct": 1.0,
            "external_move_detected_ts_ms": 123,
        },
    )
    insert_crypto_latency_opportunity(
        db,
        {
            "opportunity_id": "o1",
            "event_id": "e1",
            "token_id": "yes",
            "outcome": "Yes",
            "side": "buy",
            "amount_usd": 5,
            "fill_status": "filled",
            "risk_allowed": False,
        },
    )
    report = crypto_latency_report(db)
    assert report["events"] == 1
    assert report["opportunities"] == 1
    assert report["market_windows"] == 1
    assert crypto_latency_opportunities(db)[0]["opportunity_id"] == "o1"
    db.close()
