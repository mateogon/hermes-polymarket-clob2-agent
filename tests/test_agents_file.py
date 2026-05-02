from pathlib import Path


def test_agents_md_exists_and_contains_safety_rules():
    text = Path("AGENTS.md").read_text()
    assert "Never enable live trading" in text
    assert "pytest -q" in text
    assert "ALLOW_LIVE_TRADING" in text
