"""Diagnostics for wallet replay exit coverage."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any

from hermes_polymarket.data_sources.polymarket_data_api import WalletTrade


@dataclass(frozen=True)
class ExitCoverageReport:
    wallet: str
    total_trades: int
    buys: int
    sells: int
    unique_assets_bought: int
    unique_assets_sold: int
    buy_assets_with_sell: int
    buy_assets_without_sell: int
    conditions_with_buys: int
    conditions_with_sells: int
    likely_reasons: list[str]
    top_unclosed_assets: list[dict[str, Any]]
    side_counts: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def exit_coverage_report(wallet: str, trades: list[WalletTrade]) -> ExitCoverageReport:
    wallet_l = wallet.lower()
    scoped = [trade for trade in trades if trade.wallet.lower() == wallet_l]
    buys = [trade for trade in scoped if trade.side.upper() == "BUY"]
    sells = [trade for trade in scoped if trade.side.upper() == "SELL"]

    buy_assets = {(trade.condition_id, trade.asset_id) for trade in buys}
    sell_assets = {(trade.condition_id, trade.asset_id) for trade in sells}
    with_sell = buy_assets.intersection(sell_assets)
    without_sell = buy_assets - sell_assets

    buy_counts = Counter((trade.condition_id, trade.asset_id, trade.slug, trade.outcome) for trade in buys)
    top_unclosed: list[dict[str, Any]] = []
    for condition_id, asset_id in without_sell:
        matching = [
            (slug, outcome, count)
            for (c, a, slug, outcome), count in buy_counts.items()
            if c == condition_id and a == asset_id
        ]
        slug = matching[0][0] if matching else ""
        outcome = matching[0][1] if matching else ""
        top_unclosed.append(
            {
                "condition_id": condition_id,
                "asset_id": asset_id,
                "slug": slug,
                "outcome": outcome,
                "buy_trades": sum(count for _, _, count in matching),
            }
        )
    top_unclosed.sort(key=lambda row: row["buy_trades"], reverse=True)

    likely_reasons: list[str] = []
    if not sells:
        likely_reasons.append("no_sell_trades_observed")
    if sells and not with_sell:
        likely_reasons.append("sell_trades_exist_but_not_same_asset")
    if buys and len(without_sell) > len(with_sell) * 3:
        likely_reasons.append("many_entries_may_be_held_to_resolution_or_need_wider_backfill")
    if len(scoped) < 200:
        likely_reasons.append("small_backfill_window")

    return ExitCoverageReport(
        wallet=wallet,
        total_trades=len(scoped),
        buys=len(buys),
        sells=len(sells),
        unique_assets_bought=len(buy_assets),
        unique_assets_sold=len(sell_assets),
        buy_assets_with_sell=len(with_sell),
        buy_assets_without_sell=len(without_sell),
        conditions_with_buys=len({trade.condition_id for trade in buys}),
        conditions_with_sells=len({trade.condition_id for trade in sells}),
        likely_reasons=likely_reasons,
        top_unclosed_assets=top_unclosed[:20],
        side_counts=dict(Counter(trade.side.upper() for trade in scoped)),
    )
