from hermes_polymarket.crypto.market_resolver import infer_crypto_symbol, market_window_from_gamma_market


def test_infer_crypto_symbol():
    assert infer_crypto_symbol("Bitcoin up or down") == "btcusdt"
    assert infer_crypto_symbol("Will solana dip") == "solusdt"


def test_market_window_from_gamma_market():
    row = {
        "conditionId": "c",
        "slug": "bitcoin-up-or-down",
        "question": "Bitcoin up?",
        "tokens": ["yes", "no"],
        "active": True,
    }
    window = market_window_from_gamma_market(row)
    assert window is not None
    assert window["symbol"] == "btcusdt"
    assert window["yes_token_id"] == "yes"
