import httpx

from hermes_polymarket.crypto.watchlist_seeding import current_reference_consensus, seed_current_window_from_slug


def _json_response(payload):
    return httpx.Response(200, json=payload)


def test_current_reference_consensus_uses_two_public_sources():
    def handler(request: httpx.Request) -> httpx.Response:
        if "binance" in request.url.host:
            return _json_response({"price": "100.0"})
        if "coinbase" in request.url.host:
            return _json_response({"price": "100.05"})
        if "kraken" in request.url.host:
            return httpx.Response(500)
        raise AssertionError(str(request.url))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    price, sources, max_deviation = current_reference_consensus("btcusdt", http_client=client)

    assert price == 100.025
    assert sources == ("binance_rest", "coinbase_rest")
    assert max_deviation < 0.1


def test_seed_current_window_from_slug_resolves_gamma_and_reference():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "gamma-api.polymarket.com":
            return _json_response(
                [
                    {
                        "conditionId": "condition",
                        "slug": "bitcoin-up-or-down",
                        "question": "Bitcoin Up or Down",
                        "clobTokenIds": '["yes-token", "no-token"]',
                        "active": True,
                    }
                ]
            )
        if "binance" in request.url.host:
            return _json_response({"price": "100.0"})
        if "coinbase" in request.url.host:
            return _json_response({"price": "100.02"})
        if "kraken" in request.url.host:
            return _json_response({"result": {"XXBTZUSD": {"c": ["100.01", "1"]}}})
        raise AssertionError(str(request.url))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    seed = seed_current_window_from_slug(
        slug="bitcoin-up-or-down",
        symbol="btcusdt",
        yes_direction="up",
        duration_seconds=900,
        now_ts=123,
        http_client=client,
    )

    assert seed.condition_id == "condition"
    assert seed.yes_token_id == "yes-token"
    assert seed.up_token_id == "yes-token"
    assert seed.down_token_id == "no-token"
    assert seed.reference_price == 100.01
    assert seed.window_start_ts == 123
    assert seed.window_end_ts == 1023
    assert set(seed.consensus_sources) == {"binance_rest", "coinbase_rest", "kraken_rest"}


def test_seed_current_window_rejects_closed_gamma_market():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "gamma-api.polymarket.com":
            return _json_response(
                [
                    {
                        "conditionId": "condition",
                        "slug": "closed-window",
                        "question": "Bitcoin Up or Down",
                        "clobTokenIds": '["yes-token", "no-token"]',
                        "active": True,
                        "closed": True,
                    }
                ]
            )
        raise AssertionError(str(request.url))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        seed_current_window_from_slug(
            slug="closed-window",
            symbol="btcusdt",
            yes_direction="up",
            duration_seconds=900,
            now_ts=123,
            http_client=client,
        )
    except ValueError as exc:
        assert "not active/open" in str(exc)
    else:
        raise AssertionError("closed market should be rejected")
