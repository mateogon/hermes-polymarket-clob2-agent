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
