from hermes_polymarket.storage.crypto_watchlist import clear_crypto_market_watchlist, crypto_market_watchlist, upsert_crypto_market_watchlist, watchlist_token_ids
from hermes_polymarket.storage.db import Database


def test_crypto_watchlist_roundtrip(tmp_path):
    db = Database(tmp_path / "x.sqlite")
    db.init_schema(1000)

    upsert_crypto_market_watchlist(
        db,
        {
            "condition_id": "condition",
            "slug": "bitcoin-up-down-15m",
            "question": "Bitcoin up or down in 15 minutes?",
            "symbol": "btcusdt",
            "yes_token_id": "yes",
            "no_token_id": "no",
            "active": True,
            "discovered_at_ms": 1000,
            "raw": {"x": 1},
        },
    )

    rows = crypto_market_watchlist(db)
    assert len(rows) == 1
    assert rows[0]["symbol"] == "btcusdt"
    assert watchlist_token_ids(db) == ("yes", "no")
    assert clear_crypto_market_watchlist(db) == 1
    assert crypto_market_watchlist(db) == []
    db.close()
