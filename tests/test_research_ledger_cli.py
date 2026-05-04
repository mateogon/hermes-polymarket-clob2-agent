import json

from hermes_polymarket import cli


def test_research_hypothesis_roundtrip(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HERMES_ENV", "research")
    monkeypatch.setenv("HERMES_DATABASE_PATH", str(tmp_path / "research.sqlite3"))

    assert (
        cli.main(
            [
                "research",
                "hypothesis",
                "add",
                "--id",
                "h-xrp",
                "--strategy",
                "multi_strike_long_yes",
                "--market-family",
                "xrp_target_hit_2026",
                "--claim",
                "XRP target markets may be underpriced when realized vol is elevated.",
                "--data-quality",
                "historical_spot_fair_value_with_cost_penalty",
                "--evidence-json",
                '{"net_pnl_cost_1c": 12.01}',
                "--next-action",
                "wait for tighter book",
            ]
        )
        == 0
    )
    added = json.loads(capsys.readouterr().out)
    assert added["environment"] == "research"
    assert added["hypothesis"]["hypothesis_id"] == "h-xrp"
    assert added["hypothesis"]["evidence"]["net_pnl_cost_1c"] == 12.01

    assert cli.main(["research", "hypothesis", "update", "--id", "h-xrp", "--status", "under_evaluation", "--result-json", '{"current_gate": "wide_spread"}']) == 0
    updated = json.loads(capsys.readouterr().out)
    assert updated["hypothesis"]["status"] == "under_evaluation"
    assert updated["hypothesis"]["result"]["current_gate"] == "wide_spread"

    assert cli.main(["research", "hypothesis", "show", "--id", "h-xrp"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["hypothesis"]["strategy"] == "multi_strike_long_yes"


def test_research_experiments_report_empty(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HERMES_ENV", "research")
    monkeypatch.setenv("HERMES_DATABASE_PATH", str(tmp_path / "research.sqlite3"))

    assert cli.main(["research", "experiments", "report"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["environment"] == "research"
    assert payload["experiments"] == []
    assert payload["hypotheses"] == []
