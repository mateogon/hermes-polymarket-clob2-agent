import json

from hermes_polymarket.cli import main
from hermes_polymarket.forward_paper.campaign_summary import summarize_campaign_dbs
from hermes_polymarket.storage.db import Database
from hermes_polymarket.storage.forward_positions import insert_forward_run, insert_forward_signal


def _db(tmp_path, name: str):
    db = Database(tmp_path / name)
    db.init_schema(1000)
    return db


def _position(db: Database, *, position_id: str, run_id: str, symbol: str, fixture: bool = False, net_pnl: float = 0.0) -> None:
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


def _signal(db: Database, *, signal_id: str, run_id: str, symbol: str, final_action: str, reason: str | None, fixture: bool = False) -> None:
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


def _run(db: Database, *, run_id: str, threshold: float, signals: int, positions: int, closed: int, net_pnl: float) -> None:
    insert_forward_run(
        db,
        run_id=run_id,
        symbols=("btcusdt",),
        config={"min_move_pct": threshold},
        summary={"latency_events": signals, "paper_opportunities": positions, "fills_simulated": positions, "risk_rejected": max(0, signals - positions)},
        report={"signals": signals, "positions": positions, "closed": closed, "net_pnl": net_pnl},
        quality={"warnings": []},
        artifacts={},
        fixture=False,
        exploratory_threshold=threshold < 0.03,
    )


def test_campaign_summary_groups_multiple_dbs(tmp_path):
    db1 = _db(tmp_path, "a.sqlite3")
    _run(db1, run_id="r1", threshold=0.01, signals=2, positions=1, closed=1, net_pnl=0.5)
    _signal(db1, signal_id="s1", run_id="r1", symbol="btcusdt", final_action="paper_fill", reason="allowed")
    _signal(db1, signal_id="s2", run_id="r1", symbol="btcusdt", final_action="risk_rejected", reason="min_edge")
    _position(db1, position_id="p1", run_id="r1", symbol="btcusdt", net_pnl=0.5)
    db1.close()

    db2 = _db(tmp_path, "b.sqlite3")
    _run(db2, run_id="r2", threshold=0.02, signals=0, positions=0, closed=0, net_pnl=0)
    db2.close()

    out = summarize_campaign_dbs([tmp_path / "a.sqlite3", tmp_path / "b.sqlite3"])

    assert out["matrix_by_threshold"]["0.01"]["signals"] == 2
    assert out["matrix_by_threshold"]["0.02"]["signals"] == 0
    assert out["matrix_by_symbol"]["btcusdt"]["top_reject"] == "risk_rejected:min_edge"


def test_campaign_summary_excludes_fixture_by_default(tmp_path):
    db = _db(tmp_path, "x.sqlite3")
    _run(db, run_id="r", threshold=0.01, signals=1, positions=0, closed=0, net_pnl=0)
    _signal(db, signal_id="real", run_id="r", symbol="btcusdt", final_action="risk_rejected", reason="min_edge")
    _signal(db, signal_id="fixture", run_id="r", symbol="btcusdt", final_action="risk_rejected", reason="max_slippage", fixture=True)
    db.close()

    out = summarize_campaign_dbs([tmp_path / "x.sqlite3"])

    assert out["matrix_by_symbol"]["btcusdt"]["signals"] == 1
    assert "risk_rejected:max_slippage" not in out["matrix_by_symbol"]["btcusdt"]["rejects"]


def test_campaign_summary_cli_writes_output(tmp_path, capsys):
    db = _db(tmp_path, "x.sqlite3")
    _run(db, run_id="r", threshold=0.01, signals=0, positions=0, closed=0, net_pnl=0)
    db.close()
    output = tmp_path / "summary.json"

    assert main(["crypto-paper", "campaign-summary", "--db", str(tmp_path / "x.sqlite3"), "--output", str(output)]) == 0

    assert output.exists()
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["mode"] == "forward_paper_campaign_summary"
