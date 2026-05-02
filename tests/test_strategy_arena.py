import json

from hermes_polymarket.cli import main
from hermes_polymarket.forward_paper.strategy_arena import run_strategy_arena
from hermes_polymarket.storage.db import Database
from hermes_polymarket.storage.forward_positions import insert_forward_run, insert_forward_signal


def _db(tmp_path):
    db = Database(tmp_path / "arena.sqlite3")
    db.init_schema(1000)
    return db


def _run(db: Database, *, run_id: str, threshold: float) -> None:
    insert_forward_run(
        db,
        run_id=run_id,
        symbols=("btcusdt", "xrpusdt"),
        config={"min_move_pct": threshold},
        summary={},
        report={},
        quality={},
        artifacts={},
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


def test_strategy_arena_includes_baseline_and_threshold(tmp_path):
    db = _db(tmp_path)
    _run(db, run_id="r1", threshold=0.01)
    _signal(db, signal_id="s1", run_id="r1", symbol="btcusdt")
    _position(db, position_id="p1", run_id="r1", symbol="btcusdt", net_pnl=0.5)
    db.close()

    out = run_strategy_arena([tmp_path / "arena.sqlite3"])
    by_id = {row["strategy_id"]: row for row in out["strategies"]}

    assert "no_trade" in by_id
    assert by_id["threshold_001_exploratory"]["signals"] == 1
    assert by_id["threshold_001_exploratory"]["positions"] == 1
    assert "exploratory_threshold" in by_id["threshold_001_exploratory"]["warnings"]


def test_strategy_arena_symbol_filter_and_fixture_exclusion(tmp_path):
    db = _db(tmp_path)
    _run(db, run_id="r1", threshold=0.01)
    _signal(db, signal_id="real", run_id="r1", symbol="xrpusdt")
    _signal(db, signal_id="fixture", run_id="r1", symbol="xrpusdt", fixture=True)
    _position(db, position_id="real-pos", run_id="r1", symbol="xrpusdt", net_pnl=1.0)
    _position(db, position_id="fixture-pos", run_id="r1", symbol="xrpusdt", net_pnl=1.0, fixture=True)
    db.close()

    out = run_strategy_arena([tmp_path / "arena.sqlite3"])
    by_id = {row["strategy_id"]: row for row in out["strategies"]}

    assert by_id["xrp_only"]["signals"] == 1
    assert by_id["xrp_only"]["positions"] == 1


def test_strategy_arena_warns_no_signals_for_threshold(tmp_path):
    db = _db(tmp_path)
    _run(db, run_id="r1", threshold=0.01)
    _signal(db, signal_id="s1", run_id="r1", symbol="btcusdt")
    db.close()

    out = run_strategy_arena([tmp_path / "arena.sqlite3"])
    by_id = {row["strategy_id"]: row for row in out["strategies"]}

    assert by_id["threshold_002_candidate"]["signals"] == 0
    assert "no_signals" in by_id["threshold_002_candidate"]["warnings"]
    assert out["ready_for_strategy_claim"] is False


def test_strategy_arena_cli_run_report_compare(tmp_path, capsys):
    db = _db(tmp_path)
    _run(db, run_id="r1", threshold=0.01)
    _signal(db, signal_id="s1", run_id="r1", symbol="btcusdt")
    _position(db, position_id="p1", run_id="r1", symbol="btcusdt", net_pnl=0.5)
    db.close()
    output = tmp_path / "arena.json"

    assert main(["strategy-arena", "run", "--db", str(tmp_path / "arena.sqlite3"), "--output", str(output)]) == 0
    assert output.exists()
    run_out = json.loads(capsys.readouterr().out)
    assert run_out["mode"] == "diagnostic_paper"

    assert main(["strategy-arena", "report", "--file", str(output)]) == 0
    report_out = json.loads(capsys.readouterr().out)
    assert report_out["baseline"] == "no_trade"

    assert main(["strategy-arena", "compare", "--file", str(output), "--baseline", "no_trade"]) == 0
    compare_out = json.loads(capsys.readouterr().out)
    assert compare_out["baseline"] == "no_trade"
