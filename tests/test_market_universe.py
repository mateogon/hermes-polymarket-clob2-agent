import json

from hermes_polymarket.cli import main
from hermes_polymarket.crypto.market_universe import (
    candidate_to_watchlist_row,
    filter_universe_candidates,
    scan_market_universe,
)
from hermes_polymarket.polymarket.types import OrderBook, OrderBookLevel
from hermes_polymarket.signals.source_consensus import ConsensusPrice


def _market(**overrides):
    row = {
        "question": "Bitcoin Up or Down - 15 Minutes",
        "slug": "btc-up-or-down-15m-test",
        "conditionId": "condition",
        "outcomes": '["Up", "Down"]',
        "clobTokenIds": '["up-token", "down-token"]',
        "active": True,
        "closed": False,
        "endDate": "2027-05-03T00:00:00Z",
        "volume24hr": 1000,
    }
    row.update(overrides)
    return row


def test_scan_market_universe_classifies_crypto_market_types():
    payload = scan_market_universe(
        events=[
            {
                "slug": "event",
                "title": "Crypto event",
                "markets": [
                    _market(conditionId="updown"),
                    _market(
                        conditionId="above",
                        question="Will Bitcoin be above $100,000?",
                        slug="bitcoin-above-100000",
                        outcomes='["Yes", "No"]',
                    ),
                    _market(conditionId="other", question="Will Team A win?", slug="team-a-win"),
                ],
            }
        ],
        markets=[],
        symbols={"btcusdt"},
    )

    assert payload["classified"]["up_down"] == 1
    assert payload["classified"]["above_strike"] == 1
    assert payload["classified"]["unsupported"] == 0
    assert payload["top_candidates"][0]["score"] >= 0.8


def test_filter_universe_candidates_by_type_and_score():
    payload = {
        "candidates": [
            {"slug": "a", "market_type": "up_down", "score": 0.8},
            {"slug": "b", "market_type": "above_strike", "score": 0.9},
            {"slug": "c", "market_type": "up_down", "score": 0.5},
        ]
    }

    rows = filter_universe_candidates(payload, market_type="up_down", min_score=0.6, limit=10)

    assert [row["slug"] for row in rows] == ["a"]


def test_candidate_to_watchlist_row_requires_direction_mapping():
    candidate = scan_market_universe(events=[{"slug": "event", "title": "event", "markets": [_market()]}], markets=[])["candidates"][0]
    row = candidate_to_watchlist_row(
        candidate,
        reference=ConsensusPrice("btcusdt", 100.0, ("binance", "coinbase"), 0.01, ()),
        duration_seconds=900,
    )

    assert row is not None
    assert row["up_token_id"] == "up-token"
    assert row["down_token_id"] == "down-token"
    assert row["raw"]["reference_price"] == 100.0


def test_universe_candidates_cli_reads_artifact(tmp_path, capsys):
    path = tmp_path / "universe.json"
    path.write_text(
        json.dumps(
            {
                "candidates": [
                    {"slug": "a", "market_type": "up_down", "score": 0.8},
                    {"slug": "b", "market_type": "above_strike", "score": 0.9},
                ]
            }
        )
        + "\n"
    )

    assert main(["crypto-latency", "universe", "candidates", "--file", str(path), "--market-type", "up_down", "--min-score", "0.6"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["count"] == 1
    assert payload["candidates"][0]["slug"] == "a"


def test_universe_strike_candidates_accepts_plan_7_26_args(monkeypatch, capsys):
    class FakeGamma:
        def list_events(self, **_kwargs):
            return [
                {
                    "slug": "bitcoin-above-on-may-3",
                    "title": "Bitcoin above on May 3",
                    "markets": [
                        _market(
                            conditionId="above-78",
                            question="Will Bitcoin be above $78,000 on May 3?",
                            slug="bitcoin-above-78k-on-may-3",
                            outcomes='["Yes", "No"]',
                            clobTokenIds='["yes-token", "no-token"]',
                        )
                    ],
                }
            ]

        def close(self):
            pass

    monkeypatch.setattr("hermes_polymarket.polymarket.gamma_client.GammaClient", FakeGamma)
    monkeypatch.setattr("hermes_polymarket.crypto.watchlist_seeding.current_reference_consensus", lambda _symbol: (78500.0, ("binance", "coinbase"), 0.01))

    class FakeClob:
        def __init__(self, *_args, **_kwargs):
            pass

        def get_orderbook(self, token_id):
            return OrderBook(
                token_id=token_id,
                bids=(OrderBookLevel(0.49, 100.0),),
                asks=(OrderBookLevel(0.50, 100.0),),
            )

        def close(self):
            pass

    monkeypatch.setattr("hermes_polymarket.cli.ClobV2Client", FakeClob)

    assert main(
        [
            "crypto-latency",
            "universe",
            "strike-candidates",
            "--event-slug",
            "bitcoin-above-on-may-3",
            "--symbol",
            "btcusdt",
            "--limit",
            "20",
            "--score-l2",
            "--current-price-source",
            "consensus",
        ]
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["candidates"][0]["slug"] == "bitcoin-above-78k-on-may-3"
    assert payload["candidates"][0]["market_score"] >= 0.8
    assert payload["candidates"][0]["rest_book_ok"] is True
    assert payload["candidates"][0]["l2_quality"]["all_allowed"] is True
    assert payload["candidates"][0]["recommended"] is True
