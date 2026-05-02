from hermes_polymarket.cli import main


def test_live_cli_refuses_without_env():
    assert main(["live", "--market", "m", "--side", "YES", "--amount", "5", "--live"]) == 2


def test_weather_signal_cli_runs():
    assert main(["signal", "weather", "--mode", "paper"]) == 0

