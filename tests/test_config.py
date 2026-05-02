from hermes_polymarket.config import load_settings


def test_default_mode_is_paper_and_live_disabled():
    settings = load_settings()
    assert settings.mode == "paper"
    assert settings.allow_live_trading is False
    assert settings.max_order_usd == 10.0

