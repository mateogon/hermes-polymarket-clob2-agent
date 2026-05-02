from hermes_polymarket.backtest.replay_quality import replay_quality_warnings
from hermes_polymarket.backtest.wallet_replay_models import ExitModel, ReplayTradeResult


def _closed(i: int, pnl: float, delay: int = 0):
    return ReplayTradeResult(
        replay_trade_id=f"r{i}",
        run_id="run",
        wallet="w",
        condition_id="c",
        asset_id="a",
        outcome="Yes",
        delay_seconds=delay,
        exit_model=ExitModel.LEADER_EXIT,
        status="closed",
        pnl=pnl,
        roi=pnl / 5,
    )


def test_replay_quality_warns_small_sample():
    report = replay_quality_warnings([_closed(1, 1.0)])
    assert "small_sample" in report.warnings


def test_replay_quality_warns_one_hit_wonder():
    rows = [_closed(1, 100.0)] + [_closed(i, 1.0) for i in range(2, 10)]
    report = replay_quality_warnings(rows)
    assert "one_hit_wonder" in report.warnings


def test_replay_quality_warns_no_closed_trades():
    report = replay_quality_warnings([])
    assert "no_closed_trades" in report.warnings
