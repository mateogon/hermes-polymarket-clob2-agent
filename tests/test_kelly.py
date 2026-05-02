import pytest

from hermes_polymarket.risk.kelly import adjusted_probability, quarter_kelly_size


def test_probability_discount_moves_toward_model_but_clips():
    assert adjusted_probability(0.9, 0.5, 0.5) == pytest.approx(0.7)
    assert adjusted_probability(1.0, 0.98, 0.5) == pytest.approx(0.95)


def test_quarter_kelly_positive_edge():
    result = quarter_kelly_size(
        bankroll=1000,
        entry_price=0.5,
        model_probability=0.7,
        market_price=0.5,
        confidence_discount=0.5,
    )
    assert result.edge == pytest.approx(0.1)
    assert result.full_kelly == pytest.approx(0.2)
    assert result.quarter_kelly == pytest.approx(0.05)
    assert result.size_usd == pytest.approx(50.0)


def test_quarter_kelly_zero_when_no_edge():
    result = quarter_kelly_size(bankroll=1000, entry_price=0.6, model_probability=0.6)
    assert result.size_usd == 0.0

