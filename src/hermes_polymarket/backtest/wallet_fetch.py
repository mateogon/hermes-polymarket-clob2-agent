"""Wallet trade fetch helpers."""

from __future__ import annotations

from dataclasses import dataclass

from hermes_polymarket.backtest.wallet_replay_storage import insert_wallet_trades
from hermes_polymarket.data_sources.polymarket_data_api import PolymarketDataApi, WalletTrade
from hermes_polymarket.storage.db import Database


@dataclass(frozen=True)
class FetchPageResult:
    offset: int
    fetched: int
    inserted: int
    duplicates: int


@dataclass(frozen=True)
class FetchRunResult:
    wallet: str
    trades: list[WalletTrade]
    pages: list[FetchPageResult]

    @property
    def fetched_total(self) -> int:
        return sum(page.fetched for page in self.pages)

    @property
    def inserted_total(self) -> int:
        return sum(page.inserted for page in self.pages)

    @property
    def duplicate_total(self) -> int:
        return sum(page.duplicates for page in self.pages)


def fetch_wallet_trades_paginated(
    client: PolymarketDataApi,
    *,
    wallet: str,
    page_size: int = 100,
    max_pages: int = 10,
    limit_total: int = 1000,
    min_cash: float | None = None,
    side: str | None = None,
) -> list[WalletTrade]:
    out: list[WalletTrade] = []
    offset = 0
    for _ in range(max_pages):
        remaining = limit_total - len(out)
        if remaining <= 0:
            break
        limit = min(page_size, remaining)
        batch = client.get_trades_for_wallet(wallet, limit=limit, offset=offset, min_cash=min_cash, side=side)
        if not batch:
            break
        out.extend(batch)
        offset += limit
        if len(batch) < limit:
            break
    return out


def fetch_and_persist_wallet_trades_paginated(
    db: Database,
    client: PolymarketDataApi,
    *,
    wallet: str,
    page_size: int = 100,
    max_pages: int = 10,
    limit_total: int = 1000,
    min_cash: float | None = None,
    side: str | None = None,
) -> FetchRunResult:
    out: list[WalletTrade] = []
    pages: list[FetchPageResult] = []
    offset = 0
    for _ in range(max_pages):
        remaining = limit_total - len(out)
        if remaining <= 0:
            break
        limit = min(page_size, remaining)
        batch = client.get_trades_for_wallet(wallet, limit=limit, offset=offset, min_cash=min_cash, side=side)
        if not batch:
            break
        counts = insert_wallet_trades(db, batch)
        pages.append(
            FetchPageResult(
                offset=offset,
                fetched=counts["fetched"],
                inserted=counts["inserted"],
                duplicates=counts["duplicates"],
            )
        )
        out.extend(batch)
        offset += limit
        if len(batch) < limit:
            break
    return FetchRunResult(wallet=wallet, trades=out, pages=pages)
