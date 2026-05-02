"""Orderbook state projection from Polymarket market WebSocket events."""

from __future__ import annotations

from dataclasses import dataclass, field

from hermes_polymarket.data_sources.base import DataEvent, EventType
from hermes_polymarket.polymarket.orderbook import parse_orderbook
from hermes_polymarket.polymarket.types import OrderBook, OrderBookLevel


@dataclass
class TokenBookState:
    token_id: str
    bids: dict[float, float] = field(default_factory=dict)
    asks: dict[float, float] = field(default_factory=dict)
    market: str | None = None
    active: bool = True
    best_bid_override: float | None = None
    best_ask_override: float | None = None

    @property
    def best_bid(self) -> float | None:
        return self.best_bid_override if self.best_bid_override is not None else max(self.bids, default=None)

    @property
    def best_ask(self) -> float | None:
        return self.best_ask_override if self.best_ask_override is not None else min(self.asks, default=None)

    @property
    def spread(self) -> float | None:
        if self.best_bid is None or self.best_ask is None:
            return None
        return self.best_ask - self.best_bid

    def as_orderbook(self) -> OrderBook:
        return OrderBook(
            token_id=self.token_id,
            bids=tuple(OrderBookLevel(price, size) for price, size in sorted(self.bids.items(), reverse=True)),
            asks=tuple(OrderBookLevel(price, size) for price, size in sorted(self.asks.items())),
        )


class OrderBookState:
    def __init__(self):
        self.by_token: dict[str, TokenBookState] = {}
        self.resolved_markets: set[str] = set()

    def apply(self, event: DataEvent) -> None:
        if event.event_type == EventType.POLY_BOOK:
            self.replace_book(event)
        elif event.event_type == EventType.POLY_PRICE_CHANGE:
            self.apply_price_change(event)
        elif event.event_type == EventType.POLY_BEST_BID_ASK:
            self.apply_best_bid_ask(event)
        elif event.event_type == EventType.POLY_MARKET_RESOLVED:
            self.apply_market_resolved(event)

    def replace_book(self, event: DataEvent) -> None:
        token_id = str(event.payload.get("asset_id") or event.key)
        book = parse_orderbook(token_id, event.payload)
        state = self.by_token.setdefault(token_id, TokenBookState(token_id=token_id))
        state.market = str(event.payload.get("market") or state.market or "")
        state.bids = {level.price: level.size for level in book.bids}
        state.asks = {level.price: level.size for level in book.asks}
        state.best_bid_override = None
        state.best_ask_override = None
        state.active = True

    def apply_price_change(self, event: DataEvent) -> None:
        token_id = str(event.payload.get("asset_id") or event.key)
        state = self.by_token.setdefault(token_id, TokenBookState(token_id=token_id))
        state.market = str(event.payload.get("market") or state.market or "")
        price = float(event.payload["price"])
        size = float(event.payload["size"])
        side = str(event.payload.get("side") or "").upper()
        levels = state.bids if side == "BUY" else state.asks
        if size == 0:
            levels.pop(price, None)
        else:
            levels[price] = size
        if event.payload.get("best_bid") is not None:
            state.best_bid_override = float(event.payload["best_bid"])
        if event.payload.get("best_ask") is not None:
            state.best_ask_override = float(event.payload["best_ask"])

    def apply_best_bid_ask(self, event: DataEvent) -> None:
        token_id = str(event.payload.get("asset_id") or event.key)
        state = self.by_token.setdefault(token_id, TokenBookState(token_id=token_id))
        state.market = str(event.payload.get("market") or state.market or "")
        if event.payload.get("best_bid") is not None:
            state.best_bid_override = float(event.payload["best_bid"])
        if event.payload.get("best_ask") is not None:
            state.best_ask_override = float(event.payload["best_ask"])

    def apply_market_resolved(self, event: DataEvent) -> None:
        market = str(event.payload.get("market") or event.payload.get("condition_id") or event.key)
        self.resolved_markets.add(market)
        for state in self.by_token.values():
            if state.market == market:
                state.active = False

