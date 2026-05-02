from hermes_polymarket.crypto.directional_mapping import DirectionalToken, select_directional_token


def test_selects_up_token_for_positive_move():
    tokens = [
        DirectionalToken("ethusdt", "c", "up-token", "Up", "up"),
        DirectionalToken("ethusdt", "c", "down-token", "Down", "down"),
    ]
    selected = select_directional_token(tokens=tokens, symbol="ethusdt", move_pct=0.05)
    assert selected is not None
    assert selected.token_id == "up-token"


def test_selects_down_token_for_negative_move():
    tokens = [
        DirectionalToken("ethusdt", "c", "up-token", "Up", "up"),
        DirectionalToken("ethusdt", "c", "down-token", "Down", "down"),
    ]
    selected = select_directional_token(tokens=tokens, symbol="ethusdt", move_pct=-0.05)
    assert selected is not None
    assert selected.token_id == "down-token"
