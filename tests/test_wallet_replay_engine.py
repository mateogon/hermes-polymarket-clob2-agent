from hermes_polymarket.backtest.wallet_replay import replay_wallet_trades
from hermes_polymarket.backtest.wallet_replay_models import ReplayRunConfig
from hermes_polymarket.data_sources.polymarket_data_api import WalletTrade


WALLET = "0x55be7aa03ecfbe37aa5460db791205f7ac9ddca3"


def trade(side="BUY", ts=100, price=0.5, tx="tx"):
    return WalletTrade(
        wallet=WALLET,
        side=side,
        condition_id="c",
        asset_id="a",
        outcome="Yes",
        price=price,
        size=100,
        timestamp=ts,
        slug="slug",
        title="title",
        tx_hash=f"{tx}-{side}-{ts}",
        raw={},
    )


def test_wallet_replay_leader_buy_sell_creates_pnl_by_delay():
    config = ReplayRunConfig(wallet=WALLET, delays_seconds=(0,), paper_amount_usd=5)
    run_id, results, summary = replay_wallet_trades([trade("BUY", 100, 0.5), trade("SELL", 200, 0.7)], config, run_id="run")
    assert run_id == "run"
    assert len(results) == 1
    assert results[0].status == "closed"
    assert results[0].pnl > 0
    assert summary["data_quality"] == "historical_approx"
    assert summary["by_delay"]["0"]["win_rate"] == 1.0


def test_wallet_replay_rejects_expensive_delayed_entry():
    config = ReplayRunConfig(wallet=WALLET, delays_seconds=(2,), max_worse_entry_cents=2)
    _, results, summary = replay_wallet_trades(
        [trade("BUY", 100, 0.5, "a"), trade("BUY", 102, 0.55, "b"), trade("SELL", 200, 0.7, "c")],
        config,
        run_id="run",
    )
    assert results[0].status == "skipped"
    assert results[0].skipped_reason == "entry_too_late_or_too_expensive"
    assert summary["skipped_trades_by_reason"]["entry_too_late_or_too_expensive"] >= 1


def test_wallet_replay_marks_unresolved_without_leader_exit_pending():
    config = ReplayRunConfig(wallet=WALLET, delays_seconds=(0,))
    _, results, summary = replay_wallet_trades([trade("BUY", 100, 0.5)], config, run_id="run")
    assert results[0].status == "pending"
    assert summary["pending_trades"] == 1
