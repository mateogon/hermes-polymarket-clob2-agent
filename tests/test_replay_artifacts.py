import json

from hermes_polymarket.backtest.replay_artifacts import write_replay_artifacts_csv
from hermes_polymarket.backtest.wallet_replay_models import ExitModel, ReplayTradeResult


def test_write_replay_artifacts_csv(tmp_path):
    result = ReplayTradeResult(
        replay_trade_id="rt1",
        run_id="run",
        wallet="w",
        condition_id="c",
        asset_id="a",
        outcome="Yes",
        delay_seconds=0,
        exit_model=ExitModel.LEADER_EXIT,
        status="closed",
        pnl=1.0,
        roi=0.2,
    )
    summary = {
        "data_quality": "historical_approx",
        "by_delay": {"0": {"observed": 1, "replayed": 1, "skipped": 0, "pending": 0, "roi": 0.2, "win_rate": 1, "max_drawdown": 0, "average_worse_entry_cents": 0}},
        "skipped_trades_by_reason": {},
        "pnl_by_category": {"crypto": 1.0},
    }
    paths = write_replay_artifacts_csv(
        root=tmp_path / "run",
        run_id="run",
        summary=summary,
        results=[result],
        config={"wallet": "w"},
        quality={"warnings": ["small_sample"]},
        code_commit_sha="abc",
        config_hash="cfg",
    )
    manifest = json.loads((tmp_path / "run" / "manifest.json").read_text())
    assert manifest["quality"]["warnings"] == ["small_sample"]
    assert "replay_trade_id" in (tmp_path / "run" / "replay_trades.csv").read_text()
    assert set(paths) >= {"manifest", "summary", "replay_trades_csv", "by_delay_csv"}
