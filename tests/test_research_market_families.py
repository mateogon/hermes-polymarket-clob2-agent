import json

from hermes_polymarket import cli
from hermes_polymarket.research.market_families import classify_market_family, scan_market_families


def test_classifies_supported_market_families():
    assert classify_market_family("Bitcoin up or down in 15 minutes").family == "up_down"
    assert classify_market_family("Will Bitcoin be above $100,000?").family == "above_strike"
    assert classify_market_family("Will Ethereum be below $2,000?").family == "below_strike"
    assert classify_market_family("Will XRP reach $3.80 by December 31 2026?", current_price=2.5).family == "target_hit"
    assert classify_market_family("Will Solana dip to $100 by December 31 2026?", current_price=150).family == "dip_to"


def test_market_family_scan_reports_rejected_reason():
    out = scan_market_families(
        [
            {"question": "Will XRP reach $3.80?", "slug": "will-xrp-reach-3pt80"},
            {"question": "Will Team A win?", "slug": "team-a"},
        ],
        current_prices={"xrpusdt": 2.5},
    )

    assert out["classified"]["target_hit"] == 1
    assert out["classified"]["unsupported"] == 1
    assert out["rejected_by_reason"]["no_crypto_symbol"] == 1


def test_market_families_cli_scan_file(tmp_path, capsys):
    path = tmp_path / "universe.json"
    path.write_text(
        json.dumps(
            {
                "markets": [
                    {"question": "Will Bitcoin be above $100,000?", "slug": "bitcoin-above-100k", "conditionId": "c1"},
                    {"question": "Will Solana dip to $100?", "slug": "solana-dip-to-100", "conditionId": "c2"},
                ]
            }
        )
    )

    assert (
        cli.main(
            [
                "research",
                "market-families",
                "scan",
                "--file",
                str(path),
                "--current-prices-json",
                '{"solusdt": 150}',
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["classified"]["above_strike"] == 1
    assert payload["classified"]["dip_to"] == 1
