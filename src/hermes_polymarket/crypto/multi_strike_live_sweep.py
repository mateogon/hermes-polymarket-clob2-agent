"""Current-book multi-strike candidate sweep.

This module is paper/research-only. It discovers active Gamma candidates,
checks public CLOB REST books, and ranks venues before any paper watcher runs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import contextlib
import csv
import json

from hermes_polymarket.crypto.market_quality import evaluate_market_quality
from hermes_polymarket.crypto.market_universe import fetch_gamma_universe, filter_universe_candidates, scan_market_universe
from hermes_polymarket.crypto.multi_strike_fair_value import fair_value_target_hit
from hermes_polymarket.crypto.multi_strike_market import parse_multi_strike_target
from hermes_polymarket.crypto.watchlist_seeding import current_reference_consensus
from hermes_polymarket.polymarket.clob_v2_client import ClobV2Client
from hermes_polymarket.polymarket.gamma_client import GammaClient


@dataclass(frozen=True)
class MultiStrikeLiveSweepConfig:
    symbols: tuple[str, ...] = ("btcusdt", "ethusdt", "solusdt", "xrpusdt")
    limit_events: int = 2000
    limit_markets: int = 2000
    candidate_limit: int = 300
    min_market_score: float = 0.75
    annualized_vol: float = 0.80
    edge_threshold: float = 0.0
    min_ask: float = 0.03
    max_ask: float = 0.60
    max_spread: float = 0.01
    edge_spread_buffer: float = 0.02
    top: int = 50


def _seconds_to_expiry(row: dict[str, Any], now: datetime) -> float:
    end_date = row.get("end_date")
    if end_date:
        with contextlib.suppress(ValueError):
            parsed = datetime.fromisoformat(str(end_date).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return max(1.0, (parsed - now).total_seconds())
    return 1.0


def _reject_reasons(
    *,
    candidate: dict[str, Any],
    quality: dict[str, Any],
    edge: float | None,
    min_market_score: float,
    edge_threshold: float,
    min_ask: float,
    max_ask: float,
    max_spread: float,
    edge_spread_buffer: float,
) -> list[str]:
    reasons: list[str] = []
    market_score = float(candidate.get("score") or 0.0)
    best_ask = quality.get("best_ask")
    spread = quality.get("spread")
    if market_score < min_market_score:
        reasons.append("market_score_below_min")
    if not quality.get("allowed"):
        reasons.append(f"quality:{quality.get('reason')}")
    if best_ask is None:
        reasons.append("no_best_ask")
    elif float(best_ask) < min_ask or float(best_ask) > max_ask:
        reasons.append("ask_outside_bounds")
    if edge is None or edge < edge_threshold:
        reasons.append("edge_below_threshold")
    if spread is None:
        reasons.append("no_spread")
    elif float(spread) > max_spread + 1e-9:
        reasons.append("spread_above_max")
    if edge is not None and spread is not None and edge < float(spread) + edge_spread_buffer:
        reasons.append("edge_below_spread_buffer")
    return reasons


def _rank_score(row: dict[str, Any]) -> float:
    if not row.get("recommended"):
        return -10_000.0 + float(row.get("edge") or 0.0)
    edge = float(row.get("edge") or 0.0)
    spread = float(row.get("spread") or 0.0)
    depth = float((row.get("quality") or {}).get("depth_within_2pct_usd") or 0.0)
    market_score = float(row.get("score") or 0.0)
    return edge - spread + min(depth / 100.0, 1.0) + market_score


def run_multi_strike_live_sweep(
    *,
    settings: Any,
    config: MultiStrikeLiveSweepConfig,
) -> dict[str, Any]:
    gamma = GammaClient()
    clob = ClobV2Client(settings)
    references: dict[str, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    rejected_by_reason: dict[str, int] = {}
    book_errors: list[dict[str, Any]] = []
    try:
        events, markets = fetch_gamma_universe(
            gamma,
            limit_events=config.limit_events,
            limit_markets=config.limit_markets,
        )
        universe = scan_market_universe(events=events, markets=markets, symbols=set(config.symbols))
        candidates = filter_universe_candidates(
            universe,
            market_type="multi_strike_event",
            min_score=0.0,
            limit=config.candidate_limit,
        )
        for symbol in config.symbols:
            price, sources, max_dev = current_reference_consensus(symbol)
            references[symbol] = {
                "current_price": price,
                "sources": list(sources),
                "max_deviation_pct": max_dev,
            }
        now = datetime.now(timezone.utc)
        for candidate in candidates:
            symbol = str(candidate.get("symbol") or "")
            reference = references.get(symbol)
            if reference is None:
                continue
            token_id = candidate.get("yes_token_id")
            if not token_id:
                reasons = ["missing_yes_token_id"]
                rejected_by_reason[reasons[0]] = rejected_by_reason.get(reasons[0], 0) + 1
                rows.append({**candidate, "recommended": False, "reject_reasons": reasons})
                continue
            current_price = float(reference["current_price"])
            target = parse_multi_strike_target(f"{candidate.get('question') or ''} {candidate.get('slug') or ''}", current_price=current_price)
            target_price = candidate.get("strike_price") or (target.target_price if target is not None else None)
            if target_price is None:
                reasons = ["target_parse_failed"]
                rejected_by_reason[reasons[0]] = rejected_by_reason.get(reasons[0], 0) + 1
                rows.append({**candidate, "recommended": False, "reject_reasons": reasons})
                continue
            try:
                book = clob.get_orderbook(str(token_id))
            except Exception as exc:  # noqa: BLE001 - sweep should report per-token failures.
                reason = "book_error"
                rejected_by_reason[reason] = rejected_by_reason.get(reason, 0) + 1
                book_errors.append({"slug": candidate.get("slug"), "token_id": token_id, "error_type": type(exc).__name__, "error": str(exc)})
                rows.append({**candidate, "recommended": False, "reject_reasons": [reason], "book_error": str(exc)})
                continue
            fv = fair_value_target_hit(
                current_price=current_price,
                target_price=float(target_price),
                seconds_to_expiry=_seconds_to_expiry(candidate, now),
                annualized_vol=config.annualized_vol,
            )
            quality = evaluate_market_quality(book).to_dict()
            best_ask = quality.get("best_ask")
            edge = fv.probability_yes - float(best_ask) if best_ask is not None else None
            reasons = _reject_reasons(
                candidate=candidate,
                quality=quality,
                edge=edge,
                min_market_score=config.min_market_score,
                edge_threshold=config.edge_threshold,
                min_ask=config.min_ask,
                max_ask=config.max_ask,
                max_spread=config.max_spread,
                edge_spread_buffer=config.edge_spread_buffer,
            )
            for reason in reasons:
                rejected_by_reason[reason] = rejected_by_reason.get(reason, 0) + 1
            row = {
                **candidate,
                "current_price": current_price,
                "reference_sources": reference["sources"],
                "reference_max_deviation_pct": reference["max_deviation_pct"],
                "target_price": float(target_price),
                "annualized_vol": config.annualized_vol,
                "fair_value": fv.to_dict(),
                "quality": quality,
                "best_bid": quality.get("best_bid"),
                "best_ask": best_ask,
                "spread": quality.get("spread"),
                "edge": edge,
                "recommended": not reasons,
                "reject_reasons": reasons,
            }
            row["rank_score"] = _rank_score(row)
            rows.append(row)
        ranked = sorted(rows, key=lambda row: (bool(row.get("recommended")), float(row.get("rank_score") or -9999.0)), reverse=True)
        recommended = [row for row in ranked if row.get("recommended")]
        return {
            "mode": "multi_strike_live_sweep",
            "data_quality": "current_rest_book_research_only",
            "symbols": list(config.symbols),
            "scanned_events": universe.get("scanned_events"),
            "scanned_markets": universe.get("scanned_markets"),
            "classified": universe.get("classified"),
            "config": config.__dict__,
            "references": references,
            "candidates_seen": len(candidates),
            "rows": ranked,
            "top": ranked[: config.top],
            "recommended_count": len(recommended),
            "best": recommended[0] if recommended else None,
            "rejected_by_reason": rejected_by_reason,
            "book_errors": book_errors[:20],
            "recommendation": "run_paper_watch_best" if recommended else "do_not_run_paper_watch_no_healthy_candidate",
            "warning": "Current REST book screen only; still paper/research and not a live execution claim.",
        }
    finally:
        gamma.close()
        clob.close()


def write_live_sweep_outputs(payload: dict[str, Any], *, output: Path | None = None, csv_output: Path | None = None) -> dict[str, str]:
    paths: dict[str, str] = {}
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        paths["output"] = str(output)
    if csv_output is not None:
        csv_output.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            "recommended",
            "rank_score",
            "symbol",
            "event_slug",
            "slug",
            "target_price",
            "current_price",
            "best_bid",
            "best_ask",
            "spread",
            "edge",
            "score",
            "reject_reasons",
        ]
        with csv_output.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in payload.get("rows") or []:
                writer.writerow({field: json.dumps(row.get(field)) if field == "reject_reasons" else row.get(field) for field in fieldnames})
        paths["csv_output"] = str(csv_output)
    return paths


def load_live_sweep(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())
