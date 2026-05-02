from hermes_polymarket.polymarket.clob_v2_client import parse_market_metadata


def test_parse_v2_market_metadata_shape():
    metadata = parse_market_metadata(
        "0xabc",
        {
            "mts": "0.01",
            "mos": "5",
            "fd": {"r": "0.01", "e": "1", "to": True},
            "t": [{"t": "token-yes", "o": "YES"}, {"t": "token-no", "o": "NO"}],
        },
    )
    assert metadata.condition_id == "0xabc"
    assert metadata.min_tick_size == 0.01
    assert metadata.min_order_size == 5.0
    assert metadata.token_for_outcome("yes").token_id == "token-yes"
    assert metadata.fee_details.rate == 0.01

