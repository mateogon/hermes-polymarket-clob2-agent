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


def test_rotate_strikes_imports_top_candidate_and_clears_old(monkeypatch, tmp_path, capsys):
    class FakeGamma:
        def list_events(self, **_kwargs):
            return [
                {
                    "slug": "bitcoin-above-on-may-3",
                    "title": "Bitcoin above on May 3",
                    "markets": [
                        _market(
                            conditionId="old-condition",
                            question="Will Bitcoin be above $76,000 on May 3?",
                            slug="bitcoin-above-76k-on-may-3",
                            outcomes='["Yes", "No"]',
                            clobTokenIds='["old-yes", "old-no"]',
                        ),
                        _market(
                            conditionId="new-condition",
                            question="Will Bitcoin be above $78,000 on May 3?",
                            slug="bitcoin-above-78k-on-may-3",
                            outcomes='["Yes", "No"]',
                            clobTokenIds='["yes-token", "no-token"]',
                        ),
                    ],
                }
            ]

        def close(self):
            pass

    class FakeClob:
        def __init__(self, *_args, **_kwargs):
            pass

        def get_orderbook(self, token_id):
            if token_id.startswith("old"):
                return OrderBook(token_id=token_id, bids=(OrderBookLevel(0.98, 100),), asks=(OrderBookLevel(0.984, 100),))
            return OrderBook(token_id=token_id, bids=(OrderBookLevel(0.49, 100),), asks=(OrderBookLevel(0.50, 100),))

        def close(self):
            pass

    monkeypatch.setenv("HERMES_DATABASE_PATH", str(tmp_path / "x.sqlite3"))
    monkeypatch.setattr("hermes_polymarket.cli.GammaClient", FakeGamma)
    monkeypatch.setattr("hermes_polymarket.cli.ClobV2Client", FakeClob)
    monkeypatch.setattr("hermes_polymarket.crypto.watchlist_seeding.current_reference_consensus", lambda _symbol: (78500.0, ("binance", "coinbase"), 0.01))

    assert main(
        [
            "crypto-latency",
            "watchlist",
            "rotate-strikes",
            "--symbol",
            "btcusdt",
            "--event-slug",
            "bitcoin-above-on-may-3",
            "--max-markets",
            "1",
            "--min-score",
            "0.75",
            "--clear-existing",
        ]
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["selected"][0]["slug"] == "bitcoin-above-78k-on-may-3"
    assert payload["imported"] == 1

    assert main(["crypto-latency", "watchlist"]) == 0
    watchlist = json.loads(capsys.readouterr().out)["watchlist"]
    assert watchlist[0]["slug"] == "bitcoin-above-78k-on-may-3"
    assert watchlist[0]["strike_price"] == 78000.0
    assert '"reference_price": 78500.0' in watchlist[0]["raw_json"]


def test_wait_for_strike_stops_when_candidate_imports(monkeypatch, tmp_path, capsys):
    class FakeGamma:
        def list_events(self, **_kwargs):
            return [
                {
                    "slug": "bitcoin-above-on-may-3",
                    "title": "Bitcoin above on May 3",
                    "markets": [
                        _market(
                            conditionId="new-condition",
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

    class FakeClob:
        def __init__(self, *_args, **_kwargs):
            pass

        def get_orderbook(self, token_id):
            return OrderBook(token_id=token_id, bids=(OrderBookLevel(0.49, 100),), asks=(OrderBookLevel(0.50, 100),))

        def close(self):
            pass

    monkeypatch.setenv("HERMES_DATABASE_PATH", str(tmp_path / "x.sqlite3"))
    monkeypatch.setattr("hermes_polymarket.cli.GammaClient", FakeGamma)
    monkeypatch.setattr("hermes_polymarket.cli.ClobV2Client", FakeClob)
    monkeypatch.setattr("hermes_polymarket.crypto.watchlist_seeding.current_reference_consensus", lambda _symbol: (78500.0, ("binance", "coinbase"), 0.01))

    assert main(
        [
            "crypto-latency",
            "watchlist",
            "wait-for-strike",
            "--symbol",
            "btcusdt",
            "--event-slug",
            "bitcoin-above-on-may-3",
            "--max-markets",
            "1",
            "--min-score",
            "0.75",
            "--poll-seconds",
            "0",
            "--max-attempts",
            "3",
        ]
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "found"
    assert payload["attempts"] == 1
    assert payload["imported"] == 1
    assert payload["selected"][0]["slug"] == "bitcoin-above-78k-on-may-3"
    assert payload["smoke"] is None


def test_wait_for_strike_returns_not_found_after_max_attempts(monkeypatch, tmp_path, capsys):
    class FakeGamma:
        def list_events(self, **_kwargs):
            return [
                {
                    "slug": "bitcoin-above-on-may-3",
                    "title": "Bitcoin above on May 3",
                    "markets": [
                        _market(
                            conditionId="extreme-condition",
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

    class FakeClob:
        def __init__(self, *_args, **_kwargs):
            pass

        def get_orderbook(self, token_id):
            return OrderBook(token_id=token_id, bids=(OrderBookLevel(0.98, 100),), asks=(OrderBookLevel(0.984, 100),))

        def close(self):
            pass

    monkeypatch.setenv("HERMES_DATABASE_PATH", str(tmp_path / "x.sqlite3"))
    monkeypatch.setattr("hermes_polymarket.cli.GammaClient", FakeGamma)
    monkeypatch.setattr("hermes_polymarket.cli.ClobV2Client", FakeClob)
    monkeypatch.setattr("hermes_polymarket.crypto.watchlist_seeding.current_reference_consensus", lambda _symbol: (78500.0, ("binance", "coinbase"), 0.01))

    assert (
        main(
            [
                "crypto-latency",
                "watchlist",
                "wait-for-strike",
                "--symbol",
                "btcusdt",
                "--event-slug",
                "bitcoin-above-on-may-3",
                "--max-markets",
                "1",
                "--min-score",
                "0.75",
                "--poll-seconds",
                "0",
                "--max-attempts",
                "2",
            ]
        )
        == 2
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "not_found"
    assert payload["attempts"] == 2
    assert len(payload["attempt_log"]) == 2


def test_universe_strike_events_lists_candidate_events(monkeypatch, capsys):
    class FakeGamma:
        def list_events(self, **kwargs):
            if kwargs.get("offset", 0) > 0:
                return []
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
                        ),
                        _market(
                            conditionId="above-80",
                            question="Will Bitcoin be above $80,000 on May 3?",
                            slug="bitcoin-above-80k-on-may-3",
                            outcomes='["Yes", "No"]',
                            clobTokenIds='["yes-token-2", "no-token-2"]',
                        ),
                    ],
                }
            ]

        def list_markets(self, **_kwargs):
            return []

        def close(self):
            pass

    monkeypatch.setattr("hermes_polymarket.polymarket.gamma_client.GammaClient", FakeGamma)

    assert main(
        [
            "crypto-latency",
            "universe",
            "strike-events",
            "--symbols",
            "btcusdt",
            "--limit-events",
            "10",
            "--min-candidates",
            "2",
        ]
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["events"][0]["event_slug"] == "bitcoin-above-on-may-3"
    assert payload["events"][0]["candidate_count"] == 2
