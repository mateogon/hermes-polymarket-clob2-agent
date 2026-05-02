from hermes_polymarket.backtest.wallet_exit_diagnostics import exit_coverage_report
from hermes_polymarket.data_sources.polymarket_data_api import WalletTrade


WALLET = "0x55be7aa03ecfbe37aa5460db791205f7ac9ddca3"


def _trade(side: str, condition="c1", asset="a1", ts=1):
    return WalletTrade(
        wallet=WALLET,
        side=side,
        condition_id=condition,
        asset_id=asset,
        outcome="Yes",
        price=0.5,
        size=10,
        timestamp=ts,
        slug="slug",
        title="title",
        tx_hash=f"{side}-{condition}-{asset}-{ts}",
        raw={},
    )


def test_exit_coverage_detects_matching_sell():
    trades = [_trade("BUY"), _trade("SELL", ts=2)]
    report = exit_coverage_report(WALLET, trades)
    assert report.buys == 1
    assert report.sells == 1
    assert report.buy_assets_with_sell == 1
    assert report.buy_assets_without_sell == 0


def test_exit_coverage_detects_no_sells():
    report = exit_coverage_report(WALLET, [_trade("BUY")])
    assert "no_sell_trades_observed" in report.likely_reasons
    assert "small_backfill_window" in report.likely_reasons


def test_exit_coverage_detects_sells_for_different_assets():
    trades = [_trade("BUY", asset="a1"), _trade("SELL", asset="a2", ts=2)]
    report = exit_coverage_report(WALLET, trades)
    assert report.buy_assets_with_sell == 0
    assert "sell_trades_exist_but_not_same_asset" in report.likely_reasons
