import json

from hermes_polymarket import cli


def test_multi_strike_promote_records_rejection_in_research_ledger(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HERMES_ENV", "research")
    monkeypatch.setenv("HERMES_DATABASE_PATH", str(tmp_path / "research.sqlite3"))
    sweep_path = tmp_path / "sweep.json"
    sweep_path.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "market_slug": "xrp-target",
                        "symbol": "xrpusdt",
                        "passes_promotion_gate": False,
                        "cost_cents": 1.0,
                        "simulated_trades": 1,
                        "net_pnl": -1.0,
                    }
                ]
            }
        )
    )

    assert (
        cli.main(
            [
                "research",
                "hypothesis",
                "add",
                "--id",
                "h-promote",
                "--strategy",
                "multi_strike_long_yes",
                "--market-family",
                "xrp_target_hit_2026",
                "--claim",
                "Candidate needs promotion gate.",
                "--data-quality",
                "research_cache_public_historical",
            ]
        )
        == 0
    )
    capsys.readouterr()

    assert cli.main(["multi-strike", "promote", "--sweep-json", str(sweep_path), "--symbol", "xrpusdt", "--hypothesis-id", "h-promote"]) == 0
    promoted = json.loads(capsys.readouterr().out)
    assert promoted["hypothesis_id"] == "h-promote"
    assert promoted["promoted"] == []

    assert cli.main(["research", "hypothesis", "show", "--id", "h-promote"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["hypothesis"]["status"] == "rejected_promotion_gate"
    assert shown["hypothesis"]["result"]["promotion_status"] == "rejected_promotion_gate"
    assert shown["hypothesis"]["evidence"]["promoted_count"] == 0
