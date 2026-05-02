from hermes_polymarket.forward_paper.readiness import forward_paper_readiness
from hermes_polymarket.storage.db import Database
from hermes_polymarket.storage.forward_positions import insert_forward_signal


def _db(tmp_path):
    db = Database(tmp_path / "x.sqlite3")
    db.init_schema(1000)
    return db


def _signal(db: Database, signal_id: str, *, fixture: bool = False) -> None:
    insert_forward_signal(
        db,
        {
            "signal_id": signal_id,
            "run_id": "run",
            "symbol": "ethusdt",
            "condition_id": "condition",
            "token_id": "token",
            "outcome": "YES",
            "direction": "up",
            "external_move_ts_ms": 1000,
            "external_move_pct": 0.01,
            "final_action": "risk_rejected",
            "risk_reason": "max_slippage",
            "fill_status": "filled",
            "amount_usd": 5.0,
            "model_probability": 0.6,
            "fixture": fixture,
        },
    )


def test_readiness_false_with_zero_signals(tmp_path):
    db = _db(tmp_path)

    report = forward_paper_readiness(db)

    assert report["ready_for_arena"] is False
    assert "signals_real=0 < 30" in report["reasons"]


def test_readiness_false_with_fixture_only_data(tmp_path):
    db = _db(tmp_path)
    _signal(db, "fixture-signal", fixture=True)

    report = forward_paper_readiness(db)

    assert report["signals_real"] == 0
    assert report["ready_for_arena"] is False


def test_readiness_true_with_enough_real_signals(tmp_path):
    db = _db(tmp_path)
    for idx in range(3):
        _signal(db, f"signal-{idx}")

    report = forward_paper_readiness(db, min_signals=3, min_positions=0)

    assert report["signals_real"] == 3
    assert report["ready_for_arena"] is True


def test_readiness_v2_allows_diagnostic_arena_with_positions(tmp_path):
    db = _db(tmp_path)
    for idx in range(5):
        db.conn.execute(
            """
            INSERT INTO forward_paper_positions
              (position_id, signal_id, run_id, symbol, condition_id, token_id, outcome,
               entry_ts_ms, entry_price, shares, amount_usd, status, exit_ts_ms,
               exit_price, exit_reason, gross_pnl, net_pnl, fixture)
            VALUES (?, ?, 'run', 'btcusdt', 'c', 't', 'YES', 1, 0.5, 10, 5,
                    'closed', 2, 0.6, 'take_profit', 0.1, 0.1, 0)
            """,
            (f"pos-{idx}", f"sig-{idx}"),
        )
    db.conn.commit()

    report = forward_paper_readiness(db)

    assert report["ready_for_diagnostic_arena"] is True
    assert report["ready_for_strategy_claim"] is False
    assert report["ready_for_live_review"] is False
    assert "small_signal_sample" in report["warnings"]
