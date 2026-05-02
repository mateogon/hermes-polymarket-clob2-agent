import pytest

from hermes_polymarket.signals.btc_microstructure_signal import BtcIndicators, make_btc_signal
from hermes_polymarket.signals.llm_signal import make_llm_signal
from hermes_polymarket.signals.news_signal import make_news_signal
from hermes_polymarket.signals.weather_signal import bucket_probability, make_weather_signal


def test_weather_probability_clips_unanimous_bucket():
    assert bucket_probability([10, 11, 12], low=0, high=20) == 0.95
    signal = make_weather_signal("m", "yes", [70, 71, 72], low=69, high=73)
    assert signal.model_probability == 0.95


def test_btc_signal_is_directional_and_bounded():
    signal = make_btc_signal("btc", BtcIndicators(40, 0.1, 0.2, 0.1, 0.1, 0.0))
    assert 0.35 <= signal.model_probability <= 0.65
    assert "Directional" in signal.reason


def test_news_and_llm_require_evidence():
    with pytest.raises(ValueError):
        make_news_signal("m", "yes", 0.7, "")
    with pytest.raises(ValueError):
        make_llm_signal("m", "yes", 0.7, "rationale", [])
    assert make_news_signal("m", "yes", 0.7, "source").confidence == 0.35

