from hermes_polymarket.crypto.crypto_market_classifier import infer_symbol_from_text, is_short_duration_crypto_market


def test_infer_symbol_from_text():
    assert infer_symbol_from_text("Bitcoin up or down") == "btcusdt"
    assert infer_symbol_from_text("Ethereum 15 minute") == "ethusdt"
    assert infer_symbol_from_text("Will Solana rise?") == "solusdt"


def test_short_duration_classifier():
    assert is_short_duration_crypto_market("Bitcoin up or down in 15 minutes", "bitcoin-up-down-15m")
    assert not is_short_duration_crypto_market("Will Bitcoin hit 200k this year?", "bitcoin-200k-year")
