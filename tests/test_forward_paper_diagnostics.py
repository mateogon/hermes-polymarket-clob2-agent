import json

from hermes_polymarket.cli import main
from hermes_polymarket.config import load_settings
from hermes_polymarket.forward_paper.diagnostics import explain_forward_signal, l2_context_for_signal, signal_by_id
from hermes_polymarket.storage.db import Database
from hermes_polymarket.storage.forward_positions import forward_signals, insert_forward_signal


def _db(tmp_path):
    db = Database(tmp_path / "x.sqlite3")
    db.init_schema(1000)
    return db


def _insert_l2_book(db: Database) -> None:
    db.conn.execute(
        """
        INSERT INTO l2_book_snapshots
          (token_id, event_ts_ms, received_ts_ms, bids_json, asks_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            "token-up",
            1000,
            1000,
            json.dumps([{"price": "0.49", "size": "100"}]),
            json.dumps([{"price": "0.52", "size": "100"}]),
        ),
    )
    db.conn.commit()


def _insert_signal(db: Database, *, signal_id: str = "sig-max-slip", reason: str = "max_slippage") -> None:
    insert_forward_signal(
        db,
        {
            "signal_id": signal_id,
            "run_id": "run-1",
            "symbol": "ethusdt",
            "condition_id": "condition",
            "token_id": "token-up",
            "outcome": "YES",
            "direction": "up",
            "external_move_ts_ms": 1000,
            "external_move_pct": 0.02,
            "final_action": "risk_rejected",
            "risk_reason": reason,
            "fill_status": "filled",
            "best_bid": 0.49,
            "best_ask": 0.52,
            "spread": 0.03,
            "avg_price": 0.52,
            "shares": 9.61,
            "amount_usd": 5.0,
            "model_probability": 0.6,
            "fixture": False,
            "payload": {
                "risk_explanation": "Slippage exceeds configured maximum",
                "max_slippage": 0.02,
                "slippage": 0.0297,
            },
        },
    )


def test_explain_max_slippage_signal(tmp_path):
    db = _db(tmp_path)
    _insert_l2_book(db)
    _insert_signal(db)

    explanation = explain_forward_signal(db, "sig-max-slip", load_settings())

    assert explanation["found"] is True
    assert explanation["risk_reason"] == "max_slippage"
    assert "slippage" in explanation["why"]
    assert explanation["inputs"]["max_slippage"] == 0.02
    assert explanation["l2_context"]["book_found"] is True
    assert explanation["shadow_risk"]


def test_l2_context_reconstructs_book_around_signal(tmp_path):
    db = _db(tmp_path)
    _insert_l2_book(db)
    _insert_signal(db)

    signal = signal_by_id(db, "sig-max-slip")
    assert signal is not None
    context = l2_context_for_signal(db, signal)

    assert context["book_found"] is True
    assert context["best_bid"] == 0.49
    assert context["best_ask"] == 0.52
    assert context["top_asks"][0]["price"] == 0.52


def test_rejected_reason_filters_correctly(tmp_path):
    db = _db(tmp_path)
    _insert_signal(db, signal_id="sig-1", reason="max_slippage")
    _insert_signal(db, signal_id="sig-2", reason="min_edge")

    rows = forward_signals(db, run_id="run-1", rejected_only=True, risk_reason="max_slippage")

    assert [row["signal_id"] for row in rows] == ["sig-1"]


def test_crypto_paper_explain_cli(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "cli.sqlite3"
    db = Database(db_path)
    db.init_schema(1000)
    _insert_l2_book(db)
    _insert_signal(db)
    db.close()
    monkeypatch.setenv("HERMES_DATABASE_PATH", str(db_path))

    assert main(["crypto-paper", "explain", "--signal-id", "sig-max-slip"]) == 0

    out = json.loads(capsys.readouterr().out)
    assert out["risk_reason"] == "max_slippage"
