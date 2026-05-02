from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source_text() -> str:
    parts = []
    for path in (ROOT / "src").rglob("*.py"):
        parts.append(path.read_text())
    return "\n".join(parts)


def test_no_legacy_clob_imports_in_src():
    text = _source_text()
    assert "py_clob_client.client" in text  # import path is still official for v2 package
    assert "py_clob_client_v2" not in text
    pyproject = (ROOT / "pyproject.toml").read_text()
    assert '"py-clob-client"' not in pyproject
    assert "'py-clob-client'" not in pyproject


def test_no_v1_order_fields_in_src():
    text = _source_text()
    assert "feeRateBps" not in text
    assert "nonce" not in text
    assert "taker=" not in text
    assert '"taker"' not in text
    assert "'taker'" not in text


def test_dry_run_script_has_no_private_or_posting_path():
    text = (ROOT / "scripts" / "dry_run_order.py").read_text()
    assert "private_client_state" not in text
    assert "create_and_post" not in text
    assert "post_order" not in text


def test_learning_and_wallet_research_do_not_import_live_executor():
    checked = [
        ROOT / "src/hermes_polymarket/learning",
        ROOT / "src/hermes_polymarket/backtest",
        ROOT / "src/hermes_polymarket/signals/wallet_flow_signal.py",
        ROOT / "src/hermes_polymarket/signals/wallet_score.py",
    ]
    for path in checked:
        files = path.rglob("*.py") if path.is_dir() else [path]
        for file in files:
            assert "live_executor" not in file.read_text()


def test_crypto_latency_modules_do_not_import_live_executor():
    checked = [
        ROOT / "src/hermes_polymarket/crypto",
        ROOT / "src/hermes_polymarket/backtest/crypto_latency_opportunity.py",
        ROOT / "src/hermes_polymarket/signals/crypto_latency_detector.py",
        ROOT / "src/hermes_polymarket/signals/source_consensus.py",
        ROOT / "src/hermes_polymarket/storage/crypto_latency.py",
    ]
    for path in checked:
        files = path.rglob("*.py") if path.is_dir() else [path]
        for file in files:
            assert "live_executor" not in file.read_text()
