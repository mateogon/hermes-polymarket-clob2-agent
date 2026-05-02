from hermes_polymarket.crypto.stale_quote_gate import evaluate_stale_quote


def test_stale_quote_allows_when_bbo_unchanged():
    decision = evaluate_stale_quote(
        external_move_pct=0.05,
        bbo_before={"best_bid": 0.49, "best_ask": 0.50},
        bbo_after={"best_bid": 0.49, "best_ask": 0.505},
        max_reprice_cents=1.0,
    )
    assert decision.allowed is True
    assert decision.reason == "stale_quote"


def test_stale_quote_rejects_already_repriced():
    decision = evaluate_stale_quote(
        external_move_pct=0.05,
        bbo_before={"best_bid": 0.49, "best_ask": 0.50},
        bbo_after={"best_bid": 0.54, "best_ask": 0.55},
        max_reprice_cents=1.0,
    )
    assert decision.allowed is False
    assert decision.reason == "already_repriced"


def test_stale_quote_rejects_missing_bbo():
    decision = evaluate_stale_quote(external_move_pct=0.05, bbo_before=None, bbo_after={"best_bid": 0.49, "best_ask": 0.50})
    assert decision.allowed is False
    assert decision.reason == "missing_bbo_before"


def test_stale_quote_rejects_wide_spread():
    decision = evaluate_stale_quote(
        external_move_pct=0.05,
        bbo_before={"best_bid": 0.49, "best_ask": 0.50},
        bbo_after={"best_bid": 0.45, "best_ask": 0.51},
        max_spread_cents=4.0,
    )
    assert decision.allowed is False
    assert decision.reason == "wide_spread"
