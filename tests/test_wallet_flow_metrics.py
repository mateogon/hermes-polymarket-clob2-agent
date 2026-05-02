from hermes_polymarket.cli import main
from hermes_polymarket.data_sources.polymarket_data_api import WalletTrade
from hermes_polymarket.data_sources.wallet_registry import WalletConfig
from hermes_polymarket.polymarket.types import OrderBook, OrderBookLevel
from hermes_polymarket.signals.wallet_flow_signal import evaluate_copyability
from hermes_polymarket.storage.db import Database
from hermes_polymarket.storage.wallet_flow import record_wallet_flow_decision, wallet_flow_metrics


def _wallet():
    return WalletConfig(
        name="leader",
        address="0x55be7aa03ecfbe37aa5460db791205f7ac9ddca3",
        min_trade_size_usd=100,
        max_copy_delay_seconds=20,
        max_entry_worse_cents=2,
        categories=("crypto",),
    )


def _trade(price=0.50, size=300, ts=100):
    return WalletTrade(
        wallet="0x55be7aa03ecfbe37aa5460db791205f7ac9ddca3",
        side="BUY",
        condition_id="0x" + "a" * 64,
        asset_id="token",
        outcome="Yes",
        price=price,
        size=size,
        timestamp=ts,
        slug="slug",
        title="title",
        tx_hash="0xabc",
        raw={},
    )


def test_wallet_flow_metrics_aggregate_copyable_and_rejected(tmp_path):
    db = Database(tmp_path / "wallet.sqlite3")
    db.init_schema(1000)
    wallet = _wallet()
    book = OrderBook("token", bids=(OrderBookLevel(0.49, 100),), asks=(OrderBookLevel(0.51, 100),))

    copyable = evaluate_copyability(_trade(), book, wallet, now_ts=110, paper_amount_usd=5)
    stale = evaluate_copyability(_trade(ts=1), book, wallet, now_ts=110, paper_amount_usd=5)
    record_wallet_flow_decision(db, _trade(), copyable, wallet_name=wallet.name, categories=wallet.categories, paper_pnl=1.5)
    record_wallet_flow_decision(db, _trade(ts=1), stale, wallet_name=wallet.name, categories=wallet.categories, paper_pnl=-0.5)

    metrics = wallet_flow_metrics(db)
    assert metrics.observed_trades == 2
    assert metrics.copyable_trades == 1
    assert metrics.rejected_trades == 1
    assert metrics.rejected_by_reason["stale_wallet_trade"] == 1
    assert metrics.paper_pnl == 1.0
    assert metrics.best_category == "crypto"
    db.close()


def test_wallet_flow_report_cli_runs_empty_db(monkeypatch, tmp_path):
    monkeypatch.setenv("MODE", "paper")
    # CLI uses project DB path from config; this assertion only checks command wiring.
    assert main(["wallet-flow", "report"]) == 0
