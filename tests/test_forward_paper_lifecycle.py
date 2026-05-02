from hermes_polymarket.forward_paper.lifecycle import (
    ForwardPaperPosition,
    close_position,
    should_exit_position,
)
import pytest


def _position() -> ForwardPaperPosition:
    return ForwardPaperPosition(
        position_id="p",
        signal_id="s",
        run_id="r",
        symbol="ethusdt",
        condition_id="c",
        token_id="t",
        outcome="Yes",
        entry_ts_ms=1000,
        entry_price=0.50,
        shares=10,
        amount_usd=5,
        best_bid_at_entry=0.49,
        best_ask_at_entry=0.50,
        spread_at_entry=0.01,
    )


def test_take_profit_exit():
    pos = _position()
    should_exit, reason = should_exit_position(
        pos,
        mark_price=0.59,
        ts_ms=2000,
        take_profit_cents=8,
        stop_loss_cents=4,
        timeout_seconds=900,
    )
    assert should_exit is True
    assert reason == "take_profit"
    closed = close_position(pos, ts_ms=2000, exit_price=0.59, reason=reason)
    assert closed.net_pnl == pytest.approx(0.9)


def test_timeout_exit():
    pos = _position()
    should_exit, reason = should_exit_position(
        pos,
        mark_price=0.50,
        ts_ms=1000 + 901_000,
        take_profit_cents=8,
        stop_loss_cents=4,
        timeout_seconds=900,
    )
    assert should_exit is True
    assert reason == "timeout"
