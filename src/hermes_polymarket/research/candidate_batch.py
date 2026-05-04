"""Research-only candidate batch runner.

This is the fast loop for finding strategy candidates before any forward paper
run: discover markets, cache public history, replay from cache, and report cost
survivors. It never posts orders.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hermes_polymarket.backtest.multi_strike_historical_approx import SpotSeries, replay_yes_trade_path_with_spot
from hermes_polymarket.crypto.multi_strike_market import MultiStrikeTargetInfo, parse_multi_strike_target
from hermes_polymarket.data_sources.binance_historical import BinanceHistoricalClient
from hermes_polymarket.data_sources.polymarket_data_api import PolymarketDataApi
from hermes_polymarket.polymarket.gamma_client import GammaClient
from hermes_polymarket.research.data_cache import ResearchDataCache
from hermes_polymarket.research.market_families import classify_market_family, scan_market_families


@dataclass(frozen=True)
class CandidateBatchConfig:
    symbols: tuple[str, ...]
    families: tuple[str, ...]
    limit_events: int = 1000
    limit_markets: int = 1000
    page_size: int = 300
    candidate_limit: int = 20
    trades_limit: int = 500
    interval: str = "1m"
    amount_usd: float = 5.0
    vol_mode: str = "realized"
    vol_grid: tuple[float, ...] = (0.6, 0.8, 1.0, 1.5)
    annualized_vol: float = 0.8
    vol_window_seconds: int = 86_400
    min_annualized_vol: float = 0.20
    max_annualized_vol: float = 2.00
    edge_grid: tuple[float, ...] = (0.0, 0.01, 0.03, 0.05)
    hold_grid: tuple[int, ...] = (900, 3600, 14_400)
    cost_cents_grid: tuple[float, ...] = (0.0, 1.0, 2.0)
    min_trades: int = 10
    min_profit_factor: float = 1.05
    max_drawdown: float = 10.0
    min_cost_survival_cents: float = 1.0
    candle_padding_seconds: int = 86_400
    output_dir: Path | None = None


def run_research_candidate_batch(
    *,
    config: CandidateBatchConfig,
    cache: ResearchDataCache | None = None,
    gamma: GammaClient | None = None,
    data_api: PolymarketDataApi | None = None,
    binance: BinanceHistoricalClient | None = None,
) -> dict[str, Any]:
    cache = cache or ResearchDataCache()
    own_gamma = gamma is None
    own_data = data_api is None
    own_binance = binance is None
    gamma = gamma or GammaClient()
    data_api = data_api or PolymarketDataApi()
    binance = binance or BinanceHistoricalClient()
    output_dir = config.output_dir
    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
    rejected_by_reason: dict[str, int] = {}
    try:
        events, markets = _fetch_universe(gamma, config=config)
        universe_manifest = cache.write_gamma_universe(
            label=f"candidate_batch_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
            events=events,
            markets=markets,
            params={"limit_events": config.limit_events, "limit_markets": config.limit_markets, "page_size": config.page_size},
        )
        family_scan = scan_market_families(markets + _markets_from_events(events), current_prices={}, limit=max(config.candidate_limit * 5, 100))
        candidates = _select_candidates(family_scan.get("candidates") or [], config=config)
        candidate_reports: list[dict[str, Any]] = []
        sweeps_run = 0
        trades_cached = 0
        candles_cached = 0
        cost_survivors = 0
        for candidate in candidates:
            report = _run_candidate(
                candidate,
                config=config,
                cache=cache,
                gamma=gamma,
                data_api=data_api,
                binance=binance,
                output_dir=output_dir,
            )
            candidate_reports.append(report)
            if report.get("sweep_status") == "ok":
                sweeps_run += 1
            trades_cached += int(report.get("trades_cached") or 0)
            candles_cached += int(report.get("candles_cached") or 0)
            cost_survivors += int(report.get("cost_survivors") or 0)
            reason = report.get("rejected_reason")
            if reason:
                rejected_by_reason[str(reason)] = rejected_by_reason.get(str(reason), 0) + 1

        payload = {
            "mode": "research_candidate_batch",
            "data_quality": "research_cache_public_historical",
            "symbols": list(config.symbols),
            "families": list(config.families),
            "markets_scanned": len(markets) + sum(len(event.get("markets") or []) for event in events if isinstance(event, dict)),
            "events_scanned": len(events),
            "candidates_found": len(candidates),
            "trades_cached": trades_cached,
            "candles_cached": candles_cached,
            "sweeps_run": sweeps_run,
            "cost_survivors": cost_survivors,
            "promoted": cost_survivors,
            "promotion_scope": "historical_cost_survival_only",
            "rejected_by_reason": rejected_by_reason,
            "universe_manifest": universe_manifest,
            "candidate_reports": candidate_reports,
            "recommendation": "Run multi-strike promote current-book gate only for candidates with cost_survivors > 0.",
        }
        if output_dir:
            out = output_dir / "summary.json"
            out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
            payload["output"] = str(out)
        return payload
    finally:
        if own_gamma:
            gamma.close()
        if own_data:
            data_api.close()
        if own_binance:
            binance.close()


def _run_candidate(
    candidate: dict[str, Any],
    *,
    config: CandidateBatchConfig,
    cache: ResearchDataCache,
    gamma: GammaClient,
    data_api: PolymarketDataApi,
    binance: BinanceHistoricalClient,
    output_dir: Path | None,
) -> dict[str, Any]:
    slug = str(candidate.get("slug") or "")
    symbol = str(candidate.get("symbol") or "")
    family = str(candidate.get("family") or "")
    report: dict[str, Any] = {"slug": slug, "symbol": symbol, "family": family}
    if family not in {"target_hit", "dip_to"}:
        return {**report, "rejected_reason": "family_sweep_not_supported_yet"}
    markets = gamma.markets_by_slug(slug)
    cache.write_gamma_market(slug=slug, markets=markets, params={"slug": slug})
    if not markets:
        return {**report, "rejected_reason": "market_not_found"}
    market = markets[0]
    condition_id = str(market.get("conditionId") or market.get("condition_id") or "")
    tokens = _token_ids(market)
    yes_token = tokens[0] if tokens else ""
    if not condition_id or not yes_token:
        return {**report, "rejected_reason": "missing_condition_or_yes_token"}
    trades = data_api.get_trades(market=condition_id, limit=config.trades_limit)
    cache.write_polymarket_trades(condition_id=condition_id, trades=trades, params={"condition_id": condition_id, "limit": config.trades_limit})
    report["condition_id"] = condition_id
    report["trades_cached"] = len(trades)
    if len(trades) < config.min_trades:
        return {**report, "rejected_reason": "insufficient_trades_cached"}
    min_trade_ts_ms = min(trade.timestamp for trade in trades) * 1000
    max_trade_ts_ms = max(trade.timestamp for trade in trades) * 1000
    start_ts_ms = max(0, min_trade_ts_ms - config.candle_padding_seconds * 1000)
    end_ts_ms = max_trade_ts_ms + max(max(config.hold_grid, default=0) * 1000, config.candle_padding_seconds * 1000)
    candles = binance.get_klines_paginated(symbol=symbol, interval=config.interval, start_ts_ms=start_ts_ms, end_ts_ms=end_ts_ms)
    cache.write_binance_klines(
        symbol=symbol,
        interval=config.interval,
        start_ts_ms=start_ts_ms,
        end_ts_ms=end_ts_ms,
        candles=candles,
        params={"symbol": symbol, "interval": config.interval, "start_ts_ms": start_ts_ms, "end_ts_ms": end_ts_ms},
    )
    report["candles_cached"] = len(candles)
    if not candles:
        return {**report, "rejected_reason": "missing_spot_candles"}
    rows, market_report = _sweep_market_from_cached_inputs(
        market=market,
        trades=trades,
        candles=[(candle.open_ts_ms, candle.close) for candle in candles],
        yes_token=yes_token,
        symbol=symbol,
        family=family,
        config=config,
    )
    ranked = sorted(
        rows,
        key=lambda row: (
            bool(row.get("passes_promotion_gate")),
            float(row.get("robust_score") or 0.0),
            float(row.get("profit_factor") or 0.0),
            float(row.get("net_pnl") or 0.0),
            int(row.get("simulated_trades") or 0),
        ),
        reverse=True,
    )
    survivors = [row for row in ranked if bool(row.get("passes_promotion_gate")) and float(row.get("cost_cents") or 0.0) >= config.min_cost_survival_cents]
    sweep_payload = {
        "mode": "multi_strike_sweep_from_cache",
        "data_quality": "research_cache_public_historical",
        "market_slugs": [slug],
        "symbol": symbol,
        "markets": [market_report],
        "rows": ranked,
        "top": ranked[:20],
        "cost_survivors": survivors[:20],
    }
    sweep_path = None
    if output_dir:
        candidate_dir = output_dir / _safe(slug)
        candidate_dir.mkdir(parents=True, exist_ok=True)
        sweep_path = candidate_dir / "sweep.json"
        csv_path = candidate_dir / "sweep.csv"
        sweep_path.write_text(json.dumps(sweep_payload, indent=2, sort_keys=True) + "\n")
        _write_sweep_csv(csv_path, ranked)
    top = ranked[0] if ranked else None
    out = {
        **report,
        "sweep_status": "ok",
        "market": market_report,
        "rows": len(ranked),
        "cost_survivors": len(survivors),
        "top": _small_row(top),
        "promotion_command": _promotion_command(sweep_path, symbol) if sweep_path and survivors else None,
    }
    if not survivors:
        out["rejected_reason"] = "no_cost_survivors"
    return out


def _sweep_market_from_cached_inputs(
    *,
    market: dict[str, Any],
    trades: list[Any],
    candles: list[tuple[int, float]],
    yes_token: str,
    symbol: str,
    family: str,
    config: CandidateBatchConfig,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    end_date = market.get("endDate")
    if not end_date:
        return [], {"market_slug": market.get("slug"), "status": "missing_end_date"}
    parsed_end = datetime.fromisoformat(str(end_date).replace("Z", "+00:00"))
    if parsed_end.tzinfo is None:
        parsed_end = parsed_end.replace(tzinfo=timezone.utc)
    expiry_ts_ms = int(parsed_end.timestamp() * 1000)
    target = _target_info_for_market(market, current_price=candles[0][1])
    if target is None:
        return [], {"market_slug": market.get("slug"), "status": "target_parse_failed"}
    rows: list[dict[str, Any]] = []
    vols = config.vol_grid if config.vol_mode == "fixed" else (config.annualized_vol,)
    dynamic_vol_by_ts_ms = None
    if config.vol_mode == "realized":
        spot_series = SpotSeries(candles)
        dynamic_vol_by_ts_ms = {
            trade.timestamp * 1000: vol
            for trade in trades
            if (
                vol := spot_series.realized_annualized_vol(
                    trade.timestamp * 1000,
                    window_seconds=config.vol_window_seconds,
                    min_annualized_vol=config.min_annualized_vol,
                    max_annualized_vol=config.max_annualized_vol,
                )
            )
            is not None
        }
    for vol in vols:
        for edge in config.edge_grid:
            for hold in config.hold_grid:
                for cost in config.cost_cents_grid:
                    results, summary = replay_yes_trade_path_with_spot(
                        trades,
                        token_id=yes_token,
                        spot_prices=candles,
                        target_price=target.target_price,
                        expiry_ts_ms=expiry_ts_ms,
                        annualized_vol=vol,
                        edge_threshold=edge,
                        amount_usd=config.amount_usd,
                        hold_seconds=hold,
                        cost_cents=cost,
                        dynamic_vol_window_seconds=config.vol_window_seconds if config.vol_mode == "realized" else None,
                        min_annualized_vol=config.min_annualized_vol,
                        max_annualized_vol=config.max_annualized_vol,
                        dynamic_vol_by_ts_ms=dynamic_vol_by_ts_ms,
                    )
                    row = {
                        "market_slug": market.get("slug"),
                        "condition_id": market.get("conditionId") or market.get("condition_id"),
                        "symbol": symbol,
                        "family": family,
                        "target_price": target.target_price,
                        "target_direction": target.target_direction,
                        "annualized_vol": vol,
                        "vol_mode": config.vol_mode,
                        "vol_window_seconds": config.vol_window_seconds if config.vol_mode == "realized" else None,
                        "edge_threshold": edge,
                        "hold_seconds": hold,
                        "cost_cents": cost,
                        "amount_usd": config.amount_usd,
                        **summary,
                    }
                    row["robust_score"] = float(row["net_pnl"] or 0.0) - float(row["max_drawdown"] or 0.0)
                    row["passes_promotion_gate"] = bool(
                        int(row["simulated_trades"]) >= config.min_trades
                        and float(row["net_pnl"] or 0.0) > 0
                        and float(row["profit_factor"] or 0.0) >= config.min_profit_factor
                        and float(row["max_drawdown"] or 0.0) <= config.max_drawdown
                    )
                    rows.append(row)
    return rows, {
        "market_slug": market.get("slug"),
        "condition_id": market.get("conditionId") or market.get("condition_id"),
        "family": family,
        "target_price": target.target_price,
        "target_direction": target.target_direction,
        "observed_trades": len(trades),
        "spot_points": len(candles),
        "status": "ok",
    }


def _target_info_for_market(market: dict[str, Any], *, current_price: float) -> MultiStrikeTargetInfo | None:
    text = f"{market.get('question') or market.get('title') or ''} {market.get('slug') or ''}"
    classified = classify_market_family(text, current_price=current_price)
    if classified.family in {"target_hit", "dip_to"} and classified.target_price:
        direction = classified.comparator or ("below" if classified.family == "dip_to" else "unknown")
        return MultiStrikeTargetInfo(
            market_type="multi_strike_event",
            target_price=float(classified.target_price),
            target_direction=direction,
        )
    return parse_multi_strike_target(text, current_price=current_price)


def _fetch_universe(gamma: GammaClient, *, config: CandidateBatchConfig) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    events: list[dict[str, Any]] = []
    markets: list[dict[str, Any]] = []
    for offset in range(0, config.limit_events, config.page_size):
        limit = min(config.page_size, config.limit_events - offset)
        page = gamma.list_events(active="true", closed="false", order="volume_24hr", ascending="false", limit=limit, offset=offset)
        events.extend(page)
        if len(page) < limit:
            break
    for offset in range(0, config.limit_markets, config.page_size):
        limit = min(config.page_size, config.limit_markets - offset)
        page = gamma.list_markets(active="true", closed="false", order="volume_24hr", ascending="false", limit=limit, offset=offset)
        markets.extend(page)
        if len(page) < limit:
            break
    return events, markets


def _markets_from_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for event in events:
        for market in event.get("markets") or []:
            if isinstance(market, dict):
                out.append(market)
    return out


def _select_candidates(rows: list[Any], *, config: CandidateBatchConfig) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        slug = str(row.get("slug") or "")
        if not slug or slug in seen:
            continue
        if row.get("symbol") not in config.symbols:
            continue
        if row.get("family") not in config.families:
            continue
        if not bool(row.get("active")) or bool(row.get("closed")):
            continue
        seen.add(slug)
        selected.append(row)
        if len(selected) >= config.candidate_limit:
            break
    return selected


def _token_ids(market: dict[str, Any]) -> tuple[str, ...]:
    raw = market.get("clobTokenIds") or market.get("clob_token_ids") or []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = []
    return tuple(str(value) for value in raw if value)


def _small_row(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    keys = (
        "market_slug",
        "family",
        "target_direction",
        "cost_cents",
        "edge_threshold",
        "hold_seconds",
        "simulated_trades",
        "net_pnl",
        "profit_factor",
        "max_drawdown",
        "passes_promotion_gate",
    )
    return {key: row.get(key) for key in keys}


def _promotion_command(sweep_path: Path | None, symbol: str) -> str | None:
    if sweep_path is None:
        return None
    return f".venv/bin/python -m hermes_polymarket.cli multi-strike promote --sweep-json {sweep_path} --symbol {symbol} --min-cost-cents 1"


def _write_sweep_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "market_slug",
        "symbol",
        "family",
        "target_price",
        "target_direction",
        "annualized_vol",
        "vol_mode",
        "edge_threshold",
        "hold_seconds",
        "cost_cents",
        "simulated_trades",
        "net_pnl",
        "avg_roi",
        "win_rate",
        "profit_factor",
        "max_drawdown",
        "robust_score",
        "passes_promotion_gate",
    ]
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) for field in fieldnames})


def _safe(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in str(value)).strip("_") or "unknown"
