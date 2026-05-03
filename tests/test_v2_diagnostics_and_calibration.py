import json

from hermes_polymarket.cli import main
from hermes_polymarket.forward_paper.strike_calibration import strike_shadow_calibration
from hermes_polymarket.forward_paper.v2_diagnostics import v2_diagnostics
from hermes_polymarket.storage.db import Database
from hermes_polymarket.storage.forward_positions import insert_forward_signal


def _db(tmp_path):
    db = Database(tmp_path / "v2.sqlite3")
    db.init_schema(1000)
    return db


def _signal(db: Database, *, signal_id: str = "sig-1", payload: dict | None = None, final_action: str = "paper_fill", fixture: bool = False):
    insert_forward_signal(
        db,
        {
            "signal_id": signal_id,
            "run_id": "run-1",
            "symbol": "btcusdt",
            "condition_id": "condition",
            "token_id": "yes-token",
            "outcome": "YES",
            "direction": "above_strike",
            "external_move_ts_ms": 1,
            "external_move_pct": 0.01,
            "final_action": final_action,
            "risk_reason": "allowed" if final_action == "paper_fill" else "min_liquidity",
            "fill_status": "filled" if final_action == "paper_fill" else None,
            "best_bid": 0.50,
            "best_ask": 0.52,
            "spread": 0.02,
            "avg_price": 0.52,
            "shares": 9.6,
            "amount_usd": 5,
            "model_probability": 0.6,
            "fixture": fixture,
            "payload": payload or {},
        },
    )


def _position(db: Database, *, signal_id: str = "sig-1", pnl: float = -0.25, fixture: bool = False):
    db.conn.execute(
        """
        INSERT INTO forward_paper_positions
          (position_id, signal_id, run_id, symbol, condition_id, token_id, outcome,
           entry_ts_ms, entry_price, shares, amount_usd, status, exit_ts_ms,
           exit_price, exit_reason, gross_pnl, net_pnl, fixture)
        VALUES ('pos-1', ?, 'run-1', 'btcusdt', 'condition', 'yes-token', 'YES',
          1, 0.52, 9.6, 5, 'closed', 2, 0.49, 'run_end_mark', ?, ?, ?)
        """,
        (signal_id, pnl, pnl, int(fixture)),
    )
    db.conn.commit()


def _v2_payload(edge: float = 0.08, score: float = 0.90, bbo_change: float = 0.3):
    return {
        "strategy_version": "stale_fair_value_v2",
        "market_type": "above_strike",
        "comparator": "above",
        "strike_price": 78000,
        "current_price": 78500,
        "seconds_to_expiry": 600,
        "fair_value": {
            "probability_yes": 0.60,
            "selected_side": "YES",
            "selected_edge": edge,
            "decision": "allowed",
            "reason": "diffusion_approx",
        },
        "stale_quote": {"enabled": True, "allowed": True, "reason": "stale_quote", "bbo_change_cents": bbo_change},
        "market_score": {"score": score, "min_required": 0.75, "decision": "allowed", "reasons": ["two_sided_book"]},
        "execution": {"avg_fill_price": 0.52, "best_bid": 0.50, "best_ask": 0.52},
        "risk": {"allowed": True, "reason": "allowed", "max_slippage": 0.02, "min_edge": 0.03},
    }


def test_v2_diagnostics_groups_reasons_and_handles_old_payloads(tmp_path):
    db = _db(tmp_path)
    _signal(db, signal_id="new", payload=_v2_payload())
    _signal(db, signal_id="old", payload={"legacy": True}, final_action="risk_rejected")
    _position(db, signal_id="new")
    db.close()

    result = v2_diagnostics(db_path=tmp_path / "v2.sqlite3", run_id="run-1")

    assert result["signals"] == 2
    assert result["positions"] == 1
    assert result["fair_value_reasons"]["allowed"] == 1
    assert result["stale_quote_reasons"]["stale_quote"] == 1
    assert result["risk_reasons"]["allowed"] == 1
    assert "old_or_partial_payload_fields_seen" in result["warnings"]


def test_v2_diagnostics_cli_reads_db(tmp_path, capsys):
    db = _db(tmp_path)
    _signal(db, payload=_v2_payload())
    db.close()

    assert main(["crypto-paper", "v2-diagnostics", "--db", str(tmp_path / "v2.sqlite3")]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["fair_value_reasons"]["allowed"] == 1


def test_strike_calibration_reads_multiple_dbs_and_warns_small_sample(tmp_path):
    db = _db(tmp_path)
    _signal(db, payload=_v2_payload(edge=0.08, score=0.90))
    _position(db, pnl=0.10)
    _signal(db, signal_id="low-edge", payload=_v2_payload(edge=0.01, score=0.90))
    db.close()

    result = strike_shadow_calibration([tmp_path / "v2.sqlite3"])

    assert result["mode"] == "strike_shadow_calibration"
    assert result["base_result"]["signals"] == 2
    assert result["best_configs"]
    assert "do_not_promote" in result["best_configs"][0]["warnings"]


def test_strike_calibration_cli_writes_output(tmp_path, capsys):
    db = _db(tmp_path)
    _signal(db, payload=_v2_payload())
    _position(db)
    db.close()
    output = tmp_path / "calibration.json"

    assert main(["crypto-paper", "strike-calibration", "--db", str(tmp_path / "v2.sqlite3"), "--output", str(output)]) == 0
    assert output.exists()
    payload = json.loads(capsys.readouterr().out)
    assert payload["artifact"] == str(output)


def test_watch_v2_accepts_candidate_config(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HERMES_DATABASE_PATH", str(tmp_path / "watch.sqlite3"))

    assert main(["crypto-paper", "watch-v2", "--fixture", "--seconds", "1", "--config", "config/campaign_v2_candidate.yaml"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"]["run_id"].startswith("crypto_paper_")
