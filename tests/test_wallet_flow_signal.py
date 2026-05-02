from hermes_polymarket.data_sources.polymarket_data_api import WalletTrade
from hermes_polymarket.data_sources.wallet_registry import WalletConfig
from hermes_polymarket.polymarket.types import OrderBook, OrderBookLevel
from hermes_polymarket.signals.wallet_flow_signal import evaluate_copyability, wallet_trade_to_signal


def _wallet(**overrides):
    data = {
        "name": "leader",
        "address": "0x55be7aa03ecfbe37aa5460db791205f7ac9ddca3",
        "min_trade_size_usd": 100.0,
        "max_copy_delay_seconds": 20,
        "max_entry_worse_cents": 2.0,
    }
    data.update(overrides)
    return WalletConfig(**data)


def _trade(**overrides):
    data = {
        "wallet": "0x55be7aa03ecfbe37aa5460db791205f7ac9ddca3",
        "side": "BUY",
        "condition_id": "0x" + "a" * 64,
        "asset_id": "token",
        "outcome": "Yes",
        "price": 0.50,
        "size": 300.0,
        "timestamp": 100,
        "slug": "slug",
        "title": "title",
        "tx_hash": "0xabc",
        "raw": {},
    }
    data.update(overrides)
    return WalletTrade(**data)


def _book(ask=0.51, ask_size=100):
    return OrderBook("token", bids=(OrderBookLevel(0.49, 100),), asks=(OrderBookLevel(ask, ask_size),))


def test_wallet_flow_accepts_copyable_buy_for_paper():
    decision = evaluate_copyability(_trade(), _book(), _wallet(), now_ts=110, paper_amount_usd=5)
    assert decision.copyable is True
    assert round(decision.worse_by_cents, 2) == 1.0
    signal = wallet_trade_to_signal(_trade(), decision, wallet_score=0.5)
    assert signal is not None
    assert signal.market_id == "0x" + "a" * 64
    assert signal.confidence <= 0.45


def test_wallet_flow_rejects_stale_trade():
    decision = evaluate_copyability(_trade(), _book(), _wallet(), now_ts=130, paper_amount_usd=5)
    assert decision.copyable is False
    assert decision.reason == "stale_wallet_trade"


def test_wallet_flow_rejects_expensive_late_entry():
    decision = evaluate_copyability(_trade(), _book(ask=0.55), _wallet(), now_ts=110, paper_amount_usd=5)
    assert decision.copyable is False
    assert decision.reason == "entry_too_late_or_too_expensive"


def test_wallet_flow_rejects_small_or_sell_trade():
    small = evaluate_copyability(_trade(size=10), _book(), _wallet(), now_ts=110, paper_amount_usd=5)
    assert small.reason == "leader_trade_too_small"

    sell = evaluate_copyability(_trade(side="SELL"), _book(), _wallet(), now_ts=110, paper_amount_usd=5)
    assert sell.reason == "only_buy_copy_supported_v1"
