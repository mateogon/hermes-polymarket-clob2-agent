from hermes_polymarket.cli import main


def test_l2_recorder_fixture_cli_runs():
    assert main(["l2-recorder", "start", "--token-id", "fixture-token", "--seconds", "1", "--fixture"]) == 0
