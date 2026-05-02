from hermes_polymarket.backtest.exit_models import leader_exit, pnl_for_exit, resolution_exit, risk_exit
from hermes_polymarket.backtest.wallet_replay_models import ExitModel, ReplayRunConfig
from hermes_polymarket.data_sources.polymarket_data_api import WalletTrade
import pytest


def trade(side="BUY", ts=100, price=0.5):
    return WalletTrade(
        wallet="0x55be7aa03ecfbe37aa5460db791205f7ac9ddca3",
        side=side,
        condition_id="c",
        asset_id="a",
        outcome="Yes",
        price=price,
        size=100,
        timestamp=ts,
        slug="slug",
        title="title",
        tx_hash=f"tx-{side}-{ts}",
        raw={},
    )


def test_leader_exit_finds_later_sell_and_pnl():
    exit_result = leader_exit(trade(), [trade("SELL", 200, 0.7)])
    assert exit_result.status == "closed"
    assert exit_result.exit_price == 0.7
    pnl, roi = pnl_for_exit(entry_price=0.5, exit_price=0.7, amount_usd=5)
    assert pnl == pytest.approx(2.0)
    assert roi == pytest.approx(0.4)


def test_resolution_exit_pending_and_payout():
    assert resolution_exit(resolved_outcome=None, entry_outcome="Yes").status == "pending"
    win = resolution_exit(resolved_outcome="Yes", entry_outcome="Yes", resolved_ts=300)
    assert win.exit_model == ExitModel.RESOLUTION_EXIT
    assert win.exit_price == 1.0
    lose = resolution_exit(resolved_outcome="No", entry_outcome="Yes")
    assert lose.exit_price == 0.0


def test_risk_exit_take_profit_stop_loss_and_timeout():
    tp = risk_exit(entry_ts=100, entry_price=0.5, price_path=[(101, 0.61)])
    assert tp.reason == "take_profit"
    sl = risk_exit(entry_ts=100, entry_price=0.5, price_path=[(101, 0.44)])
    assert sl.reason == "stop_loss"
    timeout = risk_exit(entry_ts=100, entry_price=0.5, price_path=[(1000, 0.51)])
    assert timeout.reason == "timeout"


def test_replay_config_validates_mode_and_amount():
    assert ReplayRunConfig(wallet="coinman2").mode == "historical_approx"
