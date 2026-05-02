from hermes_polymarket.cli import main


def test_learning_reports_and_empty_search_run():
    assert main(["learning", "daily-report"]) == 0
    assert main(["learning", "weekly-review"]) == 0
    assert main(["learning", "hypotheses"]) == 0
    assert main(["learning", "memories", "search", "--query", "coinman2"]) == 0
