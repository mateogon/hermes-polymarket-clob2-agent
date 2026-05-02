from hermes_polymarket.learning.overfit_checks import OverfitInputs, overfit_warnings
from hermes_polymarket.learning.experiments import ExperimentTracker
from hermes_polymarket.learning.journal_schema import StrategyExperimentRecord
from hermes_polymarket.learning.reports import daily_report, render_report, weekly_review
from hermes_polymarket.storage.db import Database


def test_overfit_warnings_trigger_for_weak_evidence():
    warnings = overfit_warnings(
        OverfitInputs(
            sample_size=20,
            experiment_count=25,
            free_parameters_changed=6,
            category_pnl={"crypto": 10, "sports": 1},
            forward_paper_trades=0,
            in_sample_roi=0.2,
            out_of_sample_roi=0.01,
        )
    )
    assert "small_sample" in warnings
    assert "too_many_experiments" in warnings
    assert "category_concentration" in warnings
    assert "out_of_sample_degradation" in warnings


def test_daily_and_weekly_reports_render_empty_database(tmp_path):
    db = Database(tmp_path / "learning.sqlite3")
    db.init_schema(1000)
    daily = daily_report(db)
    weekly = weekly_review(db)
    assert daily["signals"]["total"] == 0
    assert daily["safety"]["live_trading_enabled"] is False
    assert "source_health" in render_report(weekly)
    db.close()


def test_daily_report_includes_replay_experiments(tmp_path):
    db = Database(tmp_path / "learning.sqlite3")
    db.init_schema(1000)
    ExperimentTracker(db).record(
        StrategyExperimentRecord(
            run_id="run",
            run_type="wallet_replay",
            strategy_id="wallet_flow:coinman2",
            code_commit_sha="abc",
            config_hash="cfg",
            data_quality="historical_approx",
            parameters={},
            metrics={"replayed_trades": 0, "pending_trades": 10, "quality": {"warnings": ["no_closed_trades"]}},
        )
    )
    report = daily_report(db)
    assert report["experiments"]["total"] == 1
    assert report["experiments"]["recent"][0]["quality_warnings"] == ["no_closed_trades"]
    db.close()
