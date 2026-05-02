from hermes_polymarket.learning.overfit_checks import OverfitInputs, overfit_warnings
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
