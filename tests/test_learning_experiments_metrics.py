import math

import pytest

from hermes_polymarket.learning.experiments import ExperimentTracker
from hermes_polymarket.learning.journal_schema import StrategyExperimentRecord
from hermes_polymarket.learning.metrics import (
    brier_score,
    calibration_by_bucket,
    hit_rate,
    log_loss,
    max_drawdown,
    net_pnl,
    profit_factor,
    rejected_by_reason,
    roi,
)
from hermes_polymarket.storage.db import Database


def test_experiment_tracker_roundtrip(tmp_path):
    db = Database(tmp_path / "learning.sqlite3")
    db.init_schema(1000)
    tracker = ExperimentTracker(db)
    record = StrategyExperimentRecord(
        run_id="run1",
        run_type="replay",
        strategy_id="wallet_flow",
        code_commit_sha="abc",
        config_hash="cfg",
        data_quality="historical_approx",
        parameters={"delay": 2},
        metrics={"roi": 0.1},
    )
    tracker.record(record)
    row = tracker.runs("wallet_flow")[0]
    assert row["run_id"] == "run1"
    assert row["code_commit_sha"] == "abc"
    assert row["config_hash"] == "cfg"
    db.close()


def test_financial_metrics():
    pnls = [1, -0.5, 2, -1]
    assert net_pnl(pnls) == 1.5
    assert roi(1.5, 10) == 0.15
    assert profit_factor(pnls) == 2.0
    assert max_drawdown(pnls) == 1.0
    assert hit_rate([True, False, True]) == pytest.approx(2 / 3)


def test_probability_metrics_and_calibration():
    probs = [0.6, 0.7, 0.2]
    outcomes = [True, False, False]
    assert brier_score(probs, outcomes) == pytest.approx(((0.4**2) + (0.7**2) + (0.2**2)) / 3)
    assert log_loss([0.5], [True]) == pytest.approx(-math.log(0.5))
    buckets = calibration_by_bucket(probs, outcomes, bucket_size=0.5)
    assert buckets[0]["count"] == 1
    assert buckets[1]["count"] == 2
    assert rejected_by_reason(["stale", "stale", "liquidity"]) == {"stale": 2, "liquidity": 1}
