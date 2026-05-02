from hermes_polymarket.backtest.wallet_replay_models import ExitModel, ReplayTradeResult
from hermes_polymarket.signals.wallet_score import score_wallet


def result(pnl=1.0, category="crypto", delay=15, status="closed", skipped=None):
    return ReplayTradeResult(
        replay_trade_id=f"{category}-{delay}-{pnl}-{status}",
        run_id="run",
        wallet="wallet",
        condition_id="c",
        asset_id="a",
        outcome="Yes",
        delay_seconds=delay,
        exit_model=ExitModel.LEADER_EXIT,
        status=status,
        pnl=pnl,
        roi=pnl / 5 if pnl is not None else None,
        worse_entry_cents=1.0,
        skipped_reason=skipped,
        category=category,
    )


def test_wallet_score_penalizes_one_hit_wonder():
    score = score_wallet("wallet", [result(pnl=10), result(pnl=-1), result(pnl=-1), result(pnl=-1), result(pnl=-1)])
    assert score.components["one_hit_wonder"] == 1.0


def test_wallet_score_detects_style_drift():
    rows = [result(category="crypto") for _ in range(5)] + [result(category="politics") for _ in range(5)]
    score = score_wallet("wallet", rows)
    assert score.components["style_drift"] == 1.0


def test_wallet_score_rewards_category_focus_and_delay_survival():
    rows = [result(category="crypto", delay=30, pnl=1) for _ in range(20)]
    score = score_wallet("wallet", rows)
    assert score.components["category_focus"] == 1.0
    assert score.components["copy_delay_survival"] == 1.0
    assert 0 <= score.score <= 1
