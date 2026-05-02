import json

from hermes_polymarket.cli import main
from hermes_polymarket.forward_paper.evidence_dashboard import evidence_dashboard, expand_db_globs
from hermes_polymarket.storage.db import Database
from hermes_polymarket.storage.forward_positions import insert_forward_run, insert_forward_signal


def _db(tmp_path, name: str) -> Database:
    db = Database(tmp_path / name)
    db.init_schema(1000)
    return db


def _run(db: Database, *, run_id: str, threshold: float, fixture: bool = False) -> None:
    insert_forward_run(
        db,
        run_id=run_id,
        symbols=("btcusdt", "xrpusdt"),
        config={"min_move_pct": threshold},
        summary={},
        report={},
        quality={},
        artifacts={},
        fixture=fixture,
        exploratory_threshold=threshold < 0.03,
    )


def _signal(
    db: Database,
    *,
    signal_id: str,
    run_id: str,
    symbol: str,
    final_action: str = "paper_fill",
    reason: str | None = "allowed",
    fixture: bool = False,
) -> None:
    insert_forward_signal(
        db,
        {
            "signal_id": signal_id,
            "run_id": run_id,
            "symbol": symbol,
            "condition_id": "c",
            "token_id": "t",
            "outcome": "YES",
            "direction": "up",
            "external_move_ts_ms": 1,
            "external_move_pct": 0.01,
            "final_action": final_action,
            "risk_reason": reason,
            "fill_status": "filled",
            "amount_usd": 5,
            "model_probability": 0.6,
            "fixture": fixture,
        },
    )


def _position(db: Database, *, position_id: str, run_id: str, symbol: str, net_pnl: float, fixture: bool = False) -> None:
    db.conn.execute(
        """
        INSERT INTO forward_paper_positions
          (position_id, signal_id, run_id, symbol, condition_id, token_id, outcome,
           entry_ts_ms, entry_price, shares, amount_usd, status, exit_ts_ms,
           exit_price, exit_reason, gross_pnl, net_pnl, fixture)
        VALUES (?, ?, ?, ?, 'c', 't', 'YES', 1, 0.5, 10, 5, 'closed', 2, 0.6, 'take_profit', ?, ?, ?)
        """,
        (position_id, f"sig-{position_id}", run_id, symbol, net_pnl, net_pnl, int(fixture)),
    )
    db.conn.commit()


def test_expand_db_globs_and_grouping(tmp_path):
    db1 = _db(tmp_path, "a.sqlite3")
    _run(db1, run_id="r1", threshold=0.01)
    _signal(db1, signal_id="s1", run_id="r1", symbol="btcusdt")
    _position(db1, position_id="p1", run_id="r1", symbol="btcusdt", net_pnl=0.5)
    db1.close()

    db2 = _db(tmp_path, "b.sqlite3")
    _run(db2, run_id="r2", threshold=0.015)
    _signal(db2, signal_id="s2", run_id="r2", symbol="xrpusdt", final_action="risk_rejected", reason="market_quality_rejected:thin_depth_2pct")
    db2.close()

    paths = expand_db_globs([str(tmp_path / "*.sqlite3")])
    out = evidence_dashboard(paths)

    assert out["total_runs"] == 2
    assert out["total_signals"] == 2
    assert out["by_threshold"]["0.01"]["positions"] == 1
    assert out["by_symbol"]["xrpusdt"]["signals"] == 1
    assert "thin_depth_2pct_seen" in out["by_symbol"]["xrpusdt"]["warnings"]
    assert out["readiness"]["ready_for_live_review"] is False


def test_evidence_dashboard_excludes_fixture_by_default(tmp_path):
    db = _db(tmp_path, "x.sqlite3")
    _run(db, run_id="real", threshold=0.01)
    _signal(db, signal_id="real-s", run_id="real", symbol="btcusdt")
    _position(db, position_id="real-p", run_id="real", symbol="btcusdt", net_pnl=-0.5)

    _run(db, run_id="fixture", threshold=0.01, fixture=True)
    _signal(db, signal_id="fixture-s", run_id="fixture", symbol="btcusdt", fixture=True)
    _position(db, position_id="fixture-p", run_id="fixture", symbol="btcusdt", net_pnl=5.0, fixture=True)
    db.close()

    out = evidence_dashboard([tmp_path / "x.sqlite3"])
    assert out["total_runs"] == 1
    assert out["net_pnl"] == -0.5

    with_fixture = evidence_dashboard([tmp_path / "x.sqlite3"], include_fixture=True)
    assert with_fixture["total_runs"] == 2
    assert with_fixture["net_pnl"] == 4.5


def test_evidence_dashboard_detects_dominance(tmp_path):
    db = _db(tmp_path, "x.sqlite3")
    _run(db, run_id="r1", threshold=0.015)
    _signal(db, signal_id="s1", run_id="r1", symbol="xrpusdt")
    _position(db, position_id="p1", run_id="r1", symbol="xrpusdt", net_pnl=1.0)

    _run(db, run_id="r2", threshold=0.015)
    _signal(db, signal_id="s2", run_id="r2", symbol="xrpusdt")
    _position(db, position_id="p2", run_id="r2", symbol="xrpusdt", net_pnl=0.1)
    db.close()

    out = evidence_dashboard([tmp_path / "x.sqlite3"])
    assert out["dominance"]["one_run_dominance"] is True
    assert out["dominance"]["one_trade_effect"] is True
    assert out["readiness"]["ready_for_strategy_claim"] is False


def test_evidence_dashboard_cli_writes_output(tmp_path, capsys):
    db = _db(tmp_path, "x.sqlite3")
    _run(db, run_id="r1", threshold=0.01)
    db.close()
    output = tmp_path / "evidence.json"

    assert main(["evidence-dashboard", "--db-glob", str(tmp_path / "*.sqlite3"), "--output", str(output)]) == 0

    assert output.exists()
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["mode"] == "forward_paper_evidence_dashboard"
    assert parsed["artifact"] == str(output)


def test_evidence_dashboard_reports_strategy_versions(tmp_path):
    db = _db(tmp_path, "x.sqlite3")
    _run(db, run_id="v1", threshold=0.01)
    insert_forward_run(
        db,
        run_id="v2",
        symbols=("btcusdt",),
        config={"min_move_pct": 0.01, "strategy_version": "stale_fair_value_v2", "use_fair_value": True},
        summary={},
        report={},
        quality={},
        artifacts={},
    )
    _signal(db, signal_id="s1", run_id="v1", symbol="btcusdt")
    _signal(db, signal_id="s2", run_id="v2", symbol="btcusdt")
    db.close()

    out = evidence_dashboard([tmp_path / "x.sqlite3"])
    assert out["strategy_versions"]["threshold_only_v1"]["signals"] == 1
    assert out["strategy_versions"]["stale_fair_value_v2"]["signals"] == 1
    assert out["strategy_versions"]["stale_fair_value_v2"]["status"] == "needs_forward_data"
