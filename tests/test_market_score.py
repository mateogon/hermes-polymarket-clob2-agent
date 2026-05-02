from hermes_polymarket.crypto.market_score import _token_score


def test_market_score_rewards_tight_two_sided_depth():
    score, reasons = _token_score(
        {
            "allowed": True,
            "best_bid": 0.49,
            "best_ask": 0.50,
            "spread": 0.01,
            "depth_within_2pct_usd": 30,
            "depth_within_5pct_usd": 60,
        }
    )
    assert score > 0.8
    assert "tight_spread" in reasons
    assert "good_depth_2pct" in reasons


def test_market_score_penalizes_thin_wide_market():
    score, reasons = _token_score(
        {
            "allowed": False,
            "best_bid": 0.45,
            "best_ask": 0.51,
            "spread": 0.06,
            "depth_within_2pct_usd": 1,
            "depth_within_5pct_usd": 2,
        }
    )
    assert score < 0.3
    assert "wide_spread" in reasons
    assert "thin_depth_2pct" in reasons
