from hermes_polymarket.backtest.multi_strike_historical_approx import replay_yes_trade_path
from hermes_polymarket.data_sources.polymarket_data_api import WalletTrade


def _trade(ts: int, price: float, *, token: str = "yes-token", outcome: str = "Yes") -> WalletTrade:
    return WalletTrade(
        wallet="0xabc",
        side="BUY",
        condition_id="c",
        asset_id=token,
        outcome=outcome,
        price=price,
        size=10,
        timestamp=ts,
        slug="s",
        title="t",
        tx_hash=f"tx-{ts}",
        raw={},
    )


def test_replay_yes_trade_path_uses_later_trade_exit():
    results, summary = replay_yes_trade_path(
        [_trade(100, 0.10), _trade(200, 0.15), _trade(400, 0.20)],
        token_id="yes-token",
        model_probability=0.30,
        edge_threshold=0.08,
        amount_usd=5.0,
        hold_seconds=100,
    )

    assert len(results) == 1
    assert results[0].entry_price == 0.10
    assert results[0].exit_price == 0.15
    assert results[0].pnl > 0
    assert summary["net_pnl"] > 0
