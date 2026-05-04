import json
from types import SimpleNamespace

from hermes_polymarket.crypto.multi_strike_paper import MultiStrikePaperConfig, run_multi_strike_paper_watch, select_multi_strike_candidate
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
                max_spread=0.03,
            ),
        run_id="run",
    )

    assert result["status"] == "completed"
    assert result["positions_opened"] == 1
    assert result["positions_closed"] == 1
    assert db.conn.execute("SELECT COUNT(*) AS n FROM forward_paper_signals").fetchone()["n"] == 1
    assert db.conn.execute("SELECT COUNT(*) AS n FROM forward_paper_positions").fetchone()["n"] == 1
    assert db.conn.execute("SELECT COUNT(*) AS n FROM forward_paper_runs").fetchone()["n"] == 1


def test_multi_strike_paper_watch_writes_event_log(monkeypatch, tmp_path):
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

    event_log = tmp_path / "run.events.jsonl"
    monkeypatch.setenv("HERMES_RUN_EVENT_LOG_PATH", str(event_log))
    monkeypatch.setattr("hermes_polymarket.crypto.multi_strike_paper.GammaClient", FakeGamma)
    monkeypatch.setattr("hermes_polymarket.crypto.multi_strike_paper.ClobV2Client", FakeClob)
    monkeypatch.setattr("hermes_polymarket.crypto.multi_strike_paper.current_reference_consensus", lambda _symbol: (78_700.0, ("binance", "coinbase"), 0.01))

    db = Database(tmp_path / "x.sqlite3")
    db.init_schema(1000)
    result = run_multi_strike_paper_watch(
        db=db,
        settings=SimpleNamespace(database_path=tmp_path / "x.sqlite3"),
        config=MultiStrikePaperConfig(
            event_slug="when-will-bitcoin-hit-150k",
            symbol="btcusdt",
            seconds=0,
            mark_interval_seconds=0,
            close_open_on_end=True,
            max_spread=0.03,
        ),
        run_id="run",
    )

    assert result["status"] == "completed"
    events = [line for line in event_log.read_text().splitlines() if line.strip()]
    event_names = {json.loads(line)["event"] for line in events}
    assert "process_start" in event_names
    assert "position_opened" in event_names
    assert "entry_mark_done" in event_names
    assert "run_completed_persisted" in event_names


def test_multi_strike_paper_watch_persists_no_candidate_run(monkeypatch, tmp_path):
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
                bids=(OrderBookLevel(0.01, 100.0),),
                asks=(OrderBookLevel(0.02, 1_000.0),),
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
            min_ask=0.03,
            max_spread=0.03,
        ),
        run_id="run",
    )

    assert result["status"] == "no_candidate_opened"
    row = db.conn.execute("SELECT summary_json FROM forward_paper_runs WHERE run_id = 'run'").fetchone()
    assert row is not None
    summary = json.loads(row["summary_json"])
    assert summary["status"] == "no_candidate_opened"
    assert summary["reject_counts"]


def test_multi_strike_candidate_requires_spread_aware_edge():
    class FakeClob:
        def get_orderbook(self, token_id):
            return OrderBook(
                token_id=token_id,
                bids=(OrderBookLevel(0.09, 1_000.0),),
                asks=(OrderBookLevel(0.10, 1_000.0),),
            )

    selected, considered = select_multi_strike_candidate(
        event=_event(),
        clob=FakeClob(),
        symbol="btcusdt",
        current_price=78_700.0,
        config=MultiStrikePaperConfig(
            event_slug="when-will-bitcoin-hit-150k",
            symbol="btcusdt",
            edge_threshold=0.0,
            max_spread=0.01,
            edge_spread_buffer=0.50,
        ),
    )

    assert selected is None
    assert "edge_below_spread_buffer" in considered[0]["reject_reason"]


def test_multi_strike_candidate_rejects_wide_spread():
    class FakeClob:
        def get_orderbook(self, token_id):
            return OrderBook(
                token_id=token_id,
                bids=(OrderBookLevel(0.08, 1_000.0),),
                asks=(OrderBookLevel(0.11, 1_000.0),),
            )

    selected, considered = select_multi_strike_candidate(
        event=_event(),
        clob=FakeClob(),
        symbol="btcusdt",
        current_price=78_700.0,
        config=MultiStrikePaperConfig(
            event_slug="when-will-bitcoin-hit-150k",
            symbol="btcusdt",
            edge_threshold=0.0,
            max_spread=0.01,
        ),
    )

    assert selected is None
    assert "spread_above_max" in considered[0]["reject_reason"]


def test_multi_strike_candidate_allows_one_cent_spread_with_float_noise():
    class FakeClob:
        def get_orderbook(self, token_id):
            return OrderBook(
                token_id=token_id,
                bids=(OrderBookLevel(0.09, 1_000.0),),
                asks=(OrderBookLevel(0.10, 1_000.0),),
            )

    selected, considered = select_multi_strike_candidate(
        event=_event(),
        clob=FakeClob(),
        symbol="btcusdt",
        current_price=78_700.0,
        config=MultiStrikePaperConfig(
            event_slug="when-will-bitcoin-hit-150k",
            symbol="btcusdt",
            edge_threshold=0.0,
            max_spread=0.01,
        ),
    )

    assert selected is not None
    assert considered[0]["spread"] == 0.010000000000000009
    assert considered[0]["reject_reason"] == "ok"
