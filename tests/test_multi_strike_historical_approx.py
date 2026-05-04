from hermes_polymarket.backtest.multi_strike_historical_approx import (
    price_at_or_before,
    replay_yes_trade_path,
    replay_yes_trade_path_with_spot,
)
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


def test_price_at_or_before_uses_latest_available_spot():
    assert price_at_or_before([(1000, 10.0), (2000, 20.0)], 1500) == 10.0
    assert price_at_or_before([(1000, 10.0), (2000, 20.0)], 2000) == 20.0
    assert price_at_or_before([(1000, 10.0)], 500) is None


def test_replay_yes_trade_path_with_spot_recomputes_fair_value_per_entry():
    results, summary = replay_yes_trade_path_with_spot(
        [_trade(100, 0.10), _trade(200, 0.15), _trade(400, 0.20)],
        token_id="yes-token",
        spot_prices=[(100_000, 78_000.0), (200_000, 79_000.0), (400_000, 80_000.0)],
        target_price=150_000.0,
        expiry_ts_ms=200_000_000_000,
        annualized_vol=0.80,
        edge_threshold=0.01,
        amount_usd=5.0,
        hold_seconds=100,
    )

    assert summary["data_quality"] == "historical_spot_fair_value"
    assert summary["spot_points"] == 3
    assert len(results) == 1
    assert results[0].entry_spot == 78_000.0
    assert results[0].model_probability > 0


def test_replay_yes_trade_path_with_spot_applies_cost_penalty():
    no_cost, no_cost_summary = replay_yes_trade_path_with_spot(
        [_trade(100, 0.10), _trade(200, 0.15), _trade(400, 0.20)],
        token_id="yes-token",
        spot_prices=[(100_000, 78_000.0), (200_000, 79_000.0), (400_000, 80_000.0)],
        target_price=150_000.0,
        expiry_ts_ms=200_000_000_000,
        annualized_vol=0.80,
        edge_threshold=0.01,
        amount_usd=5.0,
        hold_seconds=100,
    )
    with_cost, with_cost_summary = replay_yes_trade_path_with_spot(
        [_trade(100, 0.10), _trade(200, 0.15), _trade(400, 0.20)],
        token_id="yes-token",
        spot_prices=[(100_000, 78_000.0), (200_000, 79_000.0), (400_000, 80_000.0)],
        target_price=150_000.0,
        expiry_ts_ms=200_000_000_000,
        annualized_vol=0.80,
        edge_threshold=0.01,
        amount_usd=5.0,
        hold_seconds=100,
        cost_cents=1.0,
    )

    assert with_cost[0].entry_price == no_cost[0].entry_price + 0.01
    assert with_cost[0].exit_price == no_cost[0].exit_price - 0.01
    assert with_cost_summary["net_pnl"] < no_cost_summary["net_pnl"]
