import json

from hermes_polymarket.cli import main
from hermes_polymarket.crypto.market_universe import (
    candidate_to_watchlist_row,
    filter_universe_candidates,
    scan_market_universe,
)
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
