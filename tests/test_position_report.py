from hermes_polymarket.backtest.position_report import closed_position_report, current_position_report, trade_position_coverage


def test_closed_position_report():
    rows = [
        {"realized_pnl": 10, "total_bought": 100, "slug": "a", "outcome": "Yes"},
        {"realized_pnl": -5, "total_bought": 50, "slug": "b", "outcome": "No"},
    ]
    report = closed_position_report(rows)
    assert report["closed_positions"] == 2
    assert report["total_realized_pnl"] == 5
    assert report["win_rate"] == 0.5


def test_current_position_report():
    report = current_position_report(
        [
            {
                "condition_id": "c",
                "asset_id": "a",
                "slug": "slug",
                "outcome": "Yes",
                "current_value": 5,
                "initial_value": 4,
                "cash_pnl": 1,
                "redeemable": 1,
            }
        ]
    )
    assert report["current_positions"] == 1
    assert report["redeemable_positions"] == 1


def test_trade_position_coverage():
    trades = [{"condition_id": "c1", "asset_id": "a1"}, {"condition_id": "c2", "asset_id": "a2"}]
    current = [{"condition_id": "c1", "asset_id": "a1"}]
    closed = [{"condition_id": "c3", "asset_id": "a3"}]
    report = trade_position_coverage(trades, current, closed)
    assert report["trades_with_current_position"] == 1
    assert report["trades_with_closed_position"] == 0
    assert report["trades_with_neither"] == 1
