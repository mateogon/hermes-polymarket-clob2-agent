from hermes_polymarket.cli import main


def test_wallet_replay_cli_commands_run_empty_db():
    assert main(["wallet-flow", "replay", "--wallet", "coinman2", "--delay", "0,2", "--mode", "historical-approx"]) == 0
    assert main(["wallet-flow", "score", "--wallet", "coinman2"]) == 0
    assert main(["wallet-flow", "leaderboard"]) == 0
