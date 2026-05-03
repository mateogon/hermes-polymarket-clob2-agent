from hermes_polymarket.crypto.updown_discovery import classify_updown_market, discover_updown_from_events


def _market(**overrides):
    row = {
        "question": "Bitcoin Up or Down - 15 Minutes",
        "slug": "btc-up-or-down-15m-test",
        "conditionId": "condition",
        "outcomes": '["Up", "Down"]',
        "clobTokenIds": '["up-token", "down-token"]',
        "active": True,
        "closed": False,
        "endDate": "2026-05-03T00:00:00Z",
    }
    row.update(overrides)
    return row


def test_classify_accepts_active_crypto_updown():
    candidate, reason = classify_updown_market(_market(), event_slug="event", event_title="event title")

    assert reason == "accepted"
    assert candidate is not None
    assert candidate.symbol == "btcusdt"
    assert candidate.clob_token_ids == ("up-token", "down-token")


def test_classify_rejects_above_below_strike_market():
    candidate, reason = classify_updown_market(
        _market(question="Will Bitcoin be above $80,000?", slug="bitcoin-above-80k-on-may-3", outcomes='["Yes", "No"]')
    )

    assert candidate is None
    assert reason == "not_updown_text"


def test_classify_rejects_missing_token_pair():
    candidate, reason = classify_updown_market(_market(clobTokenIds='["only-one"]'))

    assert candidate is None
    assert reason == "not_two_clob_token_ids"


def test_discover_updown_from_events_counts_rejections():
    out = discover_updown_from_events(
        [
            {
                "slug": "event",
                "title": "Crypto event",
                "markets": [
                    _market(),
                    _market(question="Will Bitcoin be above $80,000?", slug="bitcoin-above-80k-on-may-3", outcomes='["Yes", "No"]'),
                ],
            }
        ],
        symbols={"btcusdt"},
    )

    assert out["discovered"] == 1
    assert out["markets"][0]["slug"] == "btc-up-or-down-15m-test"
    assert out["debug"]["rejected_reason_counts"]["not_updown_text"] == 1


def test_discover_filters_requested_symbols():
    out = discover_updown_from_events(
        [{"slug": "event", "title": "Crypto event", "markets": [_market()]}],
        symbols={"ethusdt"},
    )

    assert out["discovered"] == 0
    assert out["debug"]["rejected_reason_counts"]["symbol_not_requested"] == 1
