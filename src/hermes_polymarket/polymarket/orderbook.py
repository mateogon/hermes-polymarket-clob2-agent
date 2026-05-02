"""Orderbook parsing and paper fill simulation."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from hermes_polymarket.polymarket.types import Fill, FillResult, OrderBook, OrderBookLevel


def _level(raw: dict[str, Any]) -> OrderBookLevel:
    return OrderBookLevel(price=float(raw["price"]), size=float(raw["size"]))


def _levels(values: Iterable[dict[str, Any]]) -> tuple[OrderBookLevel, ...]:
    levels = tuple(_level(v) for v in values)
    for level in levels:
        if not 0 < level.price < 1:
            raise ValueError(f"Invalid orderbook price: {level.price}")
        if level.size <= 0:
            raise ValueError(f"Invalid orderbook size: {level.size}")
    return levels


def parse_orderbook(token_id: str, data: dict[str, Any]) -> OrderBook:
    bids = _levels(data.get("bids", []))
    asks = _levels(data.get("asks", []))
    timestamp = parse_timestamp(data.get("timestamp"))
    return OrderBook(token_id=token_id, bids=bids, asks=asks, timestamp=timestamp, raw=data)


def parse_timestamp(raw: Any) -> datetime | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        if isinstance(raw, (int, float)) or text.isdigit():
            value = int(float(text))
            if value > 10_000_000_000:
                return datetime.fromtimestamp(value / 1000.0, tz=timezone.utc)
            return datetime.fromtimestamp(value, tz=timezone.utc)
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def empty_fill(status: str) -> FillResult:
    return FillResult(
        filled=False,
        avg_price=0.0,
        total_cost=0.0,
        total_shares=0.0,
        fee=0.0,
        slippage=0.0,
        levels_filled=0,
        is_partial=False,
        status=status,
        fills=(),
    )


def calculate_fee_placeholder(price: float, shares: float, fee_rate: float = 0.0, exponent: float = 1.0) -> float:
    if fee_rate <= 0 or shares <= 0:
        return 0.0
    uncertainty = price * (1.0 - price)
    return fee_rate * (uncertainty ** exponent) * shares


def simulate_buy_fill(
    book: OrderBook,
    amount_usd: float,
    order_type: str = "fok",
    max_price: float | None = None,
    fee_rate: float = 0.0,
    fee_exponent: float = 1.0,
) -> FillResult:
    if amount_usd <= 0:
        return empty_fill("invalid_amount")
    if not book.asks:
        return empty_fill("empty_book")

    remaining = amount_usd
    fills: list[Fill] = []
    for idx, level in enumerate(sorted(book.asks, key=lambda x: x.price), start=1):
        if max_price is not None and level.price > max_price:
            break
        if remaining <= 0:
            break
        level_cost = level.price * level.size
        if level_cost <= remaining:
            shares = level.size
            cost = level_cost
        else:
            shares = remaining / level.price
            cost = remaining
        fills.append(Fill(price=level.price, shares=shares, value=cost, level=idx))
        remaining -= cost

    if not fills:
        return empty_fill("limit_not_crossed")

    is_partial = remaining > 1e-9
    if order_type.lower() == "fok" and is_partial:
        return empty_fill("liquidity_rejected")
    if order_type.lower() not in {"fok", "fak"}:
        return empty_fill("invalid_order_type")

    total_cost = sum(fill.value for fill in fills)
    total_shares = sum(fill.shares for fill in fills)
    avg_price = total_cost / total_shares if total_shares else 0.0
    midpoint = book.midpoint
    slippage = ((avg_price - midpoint) / midpoint) if midpoint else 0.0
    fee = calculate_fee_placeholder(avg_price, total_shares, fee_rate, fee_exponent)
    return FillResult(
        filled=not is_partial,
        avg_price=avg_price,
        total_cost=total_cost,
        total_shares=total_shares,
        fee=fee,
        slippage=slippage,
        levels_filled=len(fills),
        is_partial=is_partial,
        status="partial_fill" if is_partial else "filled",
        fills=tuple(fills),
    )


def simulate_sell_fill(
    book: OrderBook,
    shares: float,
    order_type: str = "fok",
    min_price: float | None = None,
    fee_rate: float = 0.0,
    fee_exponent: float = 1.0,
) -> FillResult:
    if shares <= 0:
        return empty_fill("invalid_amount")
    if not book.bids:
        return empty_fill("empty_book")

    remaining = shares
    fills: list[Fill] = []
    for idx, level in enumerate(sorted(book.bids, key=lambda x: x.price, reverse=True), start=1):
        if min_price is not None and level.price < min_price:
            break
        if remaining <= 0:
            break
        sold = min(level.size, remaining)
        value = sold * level.price
        fills.append(Fill(price=level.price, shares=sold, value=value, level=idx))
        remaining -= sold

    if not fills:
        return empty_fill("limit_not_crossed")

    is_partial = remaining > 1e-9
    if order_type.lower() == "fok" and is_partial:
        return empty_fill("liquidity_rejected")
    if order_type.lower() not in {"fok", "fak"}:
        return empty_fill("invalid_order_type")

    total_value = sum(fill.value for fill in fills)
    total_shares = sum(fill.shares for fill in fills)
    avg_price = total_value / total_shares if total_shares else 0.0
    midpoint = book.midpoint
    slippage = ((avg_price - midpoint) / midpoint) if midpoint else 0.0
    fee = calculate_fee_placeholder(avg_price, total_shares, fee_rate, fee_exponent)
    return FillResult(
        filled=not is_partial,
        avg_price=avg_price,
        total_cost=total_value,
        total_shares=total_shares,
        fee=fee,
        slippage=slippage,
        levels_filled=len(fills),
        is_partial=is_partial,
        status="partial_fill" if is_partial else "filled",
        fills=tuple(fills),
    )
