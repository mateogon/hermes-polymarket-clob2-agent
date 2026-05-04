import json
from types import SimpleNamespace

from hermes_polymarket import cli
from hermes_polymarket.crypto.multi_strike_live_sweep import MultiStrikeLiveSweepConfig, run_multi_strike_live_sweep
from hermes_polymarket.polymarket.types import OrderBook, OrderBookLevel


def _event():
    return {
        "slug": "when-will-bitcoin-hit-150k",
        "title": "When will Bitcoin hit 150k?",
        "markets": [
            {
                "conditionId": "june",
                "question": "Will Bitcoin hit $150k by June 30, 2026?",
                "slug": "will-bitcoin-hit-150k-by-june-30-2026",
                "outcomes": '["Yes", "No"]',
                "clobTokenIds": '["june-yes", "june-no"]',
                "active": True,
                "closed": False,
                "endDate": "2026-07-01T04:00:00Z",
                "volume24hr": 1000,
            },
            {
                "conditionId": "dec",
                "question": "Will Bitcoin hit $150k by December 31, 2026?",
                "slug": "will-bitcoin-hit-150k-by-december-31-2026",
                "outcomes": '["Yes", "No"]',
                "clobTokenIds": '["dec-yes", "dec-no"]',
                "active": True,
                "closed": False,
                "endDate": "2027-01-01T04:00:00Z",
                "volume24hr": 1000,
            },
        ],
    }


def test_live_sweep_recommends_only_current_quality_candidates(monkeypatch):
    class FakeGamma:
        def list_events(self, **_kwargs):
            return [_event()]

        def list_markets(self, **_kwargs):
            return []

        def close(self):
            pass

    class FakeClob:
        def __init__(self, *_args, **_kwargs):
            pass

        def get_orderbook(self, token_id):
            if token_id == "june-yes":
                return OrderBook(
                    token_id=token_id,
                    bids=(OrderBookLevel(0.016, 100.0),),
                    asks=(OrderBookLevel(0.017, 1000.0),),
                )
            return OrderBook(
                token_id=token_id,
                bids=(OrderBookLevel(0.08, 1000.0),),
                asks=(OrderBookLevel(0.09, 1000.0),),
            )

        def close(self):
            pass

    monkeypatch.setattr("hermes_polymarket.crypto.multi_strike_live_sweep.GammaClient", FakeGamma)
    monkeypatch.setattr("hermes_polymarket.crypto.multi_strike_live_sweep.ClobV2Client", FakeClob)
    monkeypatch.setattr(
        "hermes_polymarket.crypto.multi_strike_live_sweep.current_reference_consensus",
        lambda _symbol: (80_000.0, ("binance", "coinbase"), 0.01),
    )

    payload = run_multi_strike_live_sweep(
        settings=SimpleNamespace(),
        config=MultiStrikeLiveSweepConfig(
            symbols=("btcusdt",),
            limit_events=10,
            limit_markets=0,
            min_ask=0.03,
            max_spread=0.01,
            edge_spread_buffer=0.02,
        ),
    )

    assert payload["mode"] == "multi_strike_live_sweep"
    assert payload["recommended_count"] == 1
    assert payload["best"]["slug"] == "will-bitcoin-hit-150k-by-december-31-2026"
    rejected = [row for row in payload["rows"] if row["slug"] == "will-bitcoin-hit-150k-by-june-30-2026"][0]
    assert "ask_outside_bounds" in rejected["reject_reasons"]


def test_paper_watch_best_does_not_run_without_recommended_candidate(tmp_path, capsys):
    sweep = tmp_path / "sweep.json"
    sweep.write_text(json.dumps({"mode": "multi_strike_live_sweep", "rows": []}) + "\n")

    assert cli.main(["multi-strike", "paper-watch-best", "--sweep-json", str(sweep)]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "no_recommended_candidate"
    assert payload["recommendation"] == "do_not_run_paper_watch"
