from hermes_polymarket.cli import main


def test_live_cli_refuses_without_env():
    assert main(["live", "--market", "m", "--side", "YES", "--amount", "5", "--live"]) == 2


def test_weather_signal_cli_runs():
    assert main(["signal", "weather", "--mode", "paper"]) == 0


def test_dry_run_fixture_cli_runs_without_network():
    assert main(["dry-run", "--market", "fixture-market", "--side", "YES", "--amount", "5", "--fixture"]) == 0


def test_dry_run_requires_identifier():
    assert main(["dry-run", "--side", "YES", "--amount", "5"]) == 2
