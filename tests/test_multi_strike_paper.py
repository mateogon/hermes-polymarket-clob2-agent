from types import SimpleNamespace

from hermes_polymarket.crypto.multi_strike_paper import MultiStrikePaperConfig, run_multi_strike_paper_watch
from hermes_polymarket.polymarket.types import OrderBook, OrderBookLevel
from hermes_polymarket.storage.db import Database


def _event():
    return {
        "slug": "when-will-bitcoin-hit-150k",
        "title": "When will Bitcoin hit 150k?",
        "markets": [
            {
                "conditionId": "c",
                "question": "Will Bitcoin hit $150k by December 31, 2026?",
                "slug": "will-bitcoin-hit-150k-by-december-31-2026",
                "outcomes": '["Yes", "No"]',
                "clobTokenIds": '["yes-token", "no-token"]',
                "active": True,
                "closed": False,
                "endDate": "2027-01-01T04:00:00Z",
                "volume24hr": 1000,
            }
        ],
    }


def test_multi_strike_paper_watch_opens_and_marks(monkeypatch, tmp_path):
    class FakeGamma:
        def list_events(self, **_kwargs):
            return [_event()]

        def close(self):
            pass

    class FakeClob:
        def __init__(self, *_args, **_kwargs):
            pass

        def get_orderbook(self, token_id):
            return OrderBook(
                token_id=token_id,
                bids=(OrderBookLevel(0.11, 100.0),),
                asks=(OrderBookLevel(0.13, 1_000.0),),
            )

        def close(self):
            pass

    monkeypatch.setattr("hermes_polymarket.crypto.multi_strike_paper.GammaClient", FakeGamma)
    monkeypatch.setattr("hermes_polymarket.crypto.multi_strike_paper.ClobV2Client", FakeClob)
    monkeypatch.setattr("hermes_polymarket.crypto.multi_strike_paper.current_reference_consensus", lambda _symbol: (78_700.0, ("binance", "coinbase"), 0.01))

    db = Database(tmp_path / "x.sqlite3")
    db.init_schema(1000)
    result = run_multi_strike_paper_watch(
        db=db,
        settings=SimpleNamespace(),
        config=MultiStrikePaperConfig(
            event_slug="when-will-bitcoin-hit-150k",
            symbol="btcusdt",
            seconds=0,
            mark_interval_seconds=0,
            close_open_on_end=True,
        ),
        run_id="run",
    )

    assert result["status"] == "completed"
    assert result["positions_opened"] == 1
    assert result["positions_closed"] == 1
    assert db.conn.execute("SELECT COUNT(*) AS n FROM forward_paper_signals").fetchone()["n"] == 1
    assert db.conn.execute("SELECT COUNT(*) AS n FROM forward_paper_positions").fetchone()["n"] == 1
    assert db.conn.execute("SELECT COUNT(*) AS n FROM forward_paper_runs").fetchone()["n"] == 1
