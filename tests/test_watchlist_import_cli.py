import json

from hermes_polymarket.cli import main


def test_watchlist_import_cli(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "x.sqlite3"
    watchlist = tmp_path / "watchlist.yaml"
    watchlist.write_text(
        """
markets:
  - symbol: ethusdt
    slug: eth-test
    condition_id: "condition"
    yes_token_id: "yes-token"
    no_token_id: "no-token"
    yes_direction: up
""".strip()
        + "\n"
    )
    monkeypatch.setenv("HERMES_DATABASE_PATH", str(db_path))

    assert main(["crypto-latency", "watchlist", "import", "--file", str(watchlist)]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "imported"
    assert payload["imported"] == 1
    assert payload["watchlist"][0]["up_token_id"] == "yes-token"
    assert payload["watchlist"][0]["down_token_id"] == "no-token"


def test_watchlist_disable_enable_and_health_cli(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "x.sqlite3"
    watchlist = tmp_path / "watchlist.yaml"
    watchlist.write_text(
        """
markets:
  - symbol: ethusdt
    slug: eth-test
    condition_id: "condition"
    yes_token_id: "yes-token"
    no_token_id: "no-token"
    yes_direction: up
""".strip()
        + "\n"
    )
    monkeypatch.setenv("HERMES_DATABASE_PATH", str(db_path))
    assert main(["crypto-latency", "watchlist", "import", "--file", str(watchlist)]) == 0
    capsys.readouterr()

    assert main(["crypto-latency", "watchlist", "health"]) == 0
    health = json.loads(capsys.readouterr().out)
    assert health["markets"][0]["recommended_action"] == "disable_or_replace_market"

    assert main(["crypto-latency", "watchlist", "disable", "--condition-id", "condition"]) == 0
    disabled = json.loads(capsys.readouterr().out)
    assert disabled["updated"] == 1

    assert main(["crypto-latency", "watchlist", "enable", "--condition-id", "condition"]) == 0
    enabled = json.loads(capsys.readouterr().out)
    assert enabled["updated"] == 1


def test_watchlist_prune_bad_dry_run(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "x.sqlite3"
    watchlist = tmp_path / "watchlist.yaml"
    watchlist.write_text(
        """
markets:
  - symbol: ethusdt
    slug: eth-test
    condition_id: "condition"
    yes_token_id: "yes-token"
    no_token_id: "no-token"
    yes_direction: up
""".strip()
        + "\n"
    )
    monkeypatch.setenv("HERMES_DATABASE_PATH", str(db_path))
    assert main(["crypto-latency", "watchlist", "import", "--file", str(watchlist)]) == 0
    capsys.readouterr()

    assert main(["crypto-latency", "watchlist", "prune-bad", "--dry-run"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "dry_run"
    assert payload["disabled"] == ["condition"]
