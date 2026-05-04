import json

from hermes_polymarket import cli
from hermes_polymarket.config import PROJECT_ROOT


def test_environment_show_research(capsys):
    assert cli.main(["environment", "show", "--env", "research"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["environment"] == "research"
    assert payload["mode"] == "research"
    assert payload["database_path"] == str(PROJECT_ROOT / "data/research/research.sqlite3")
    assert payload["artifact_dir"] == str(PROJECT_ROOT / "artifacts/research")
    assert payload["allow_live_trading"] is False


def test_environment_show_trading_real_forces_live_disabled(monkeypatch, capsys):
    monkeypatch.setenv("ALLOW_LIVE_TRADING", "true")

    assert cli.main(["environment", "show", "--env", "trading_real"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["environment"] == "trading_real"
    assert payload["allow_live_trading"] is False
    assert payload["requires_pre_live_audit"] is True
