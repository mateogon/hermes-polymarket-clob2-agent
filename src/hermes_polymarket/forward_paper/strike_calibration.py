"""Shadow calibration for Campaign v2 strike signals.

This module reads persisted paper-only signals and closed/marked positions. It
does not write signals, positions, orders, or DB state.
"""

from __future__ import annotations

import glob
import json
import sqlite3
from itertools import product
from pathlib import Path
from typing import Any

from hermes_polymarket.crypto.strike_fair_value import fair_value_above_strike, fair_value_below_strike


def expand_db_globs(patterns: list[str]) -> list[str]:
    paths: list[str] = []
    for pattern in patterns:
        matches = sorted(glob.glob(pattern))
        paths.extend(matches if matches else [pattern])
    return list(dict.fromkeys(paths))


def _connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _loads(value: Any) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _load_rows(db_paths: list[str | Path], *, include_fixture: bool = False) -> tuple[list[dict[str, Any]], dict[tuple[str, str], dict[str, Any]]]:
    signals: list[dict[str, Any]] = []
    positions: dict[tuple[str, str], dict[str, Any]] = {}
    for raw_path in db_paths:
        db_path = str(raw_path)
        if not Path(db_path).exists():
            continue
        conn = _connect(db_path)
        try:
            if _has_table(conn, "forward_paper_signals"):
                where = "" if include_fixture else "WHERE fixture = 0"
                for row in conn.execute(f"SELECT * FROM forward_paper_signals {where}"):
                    data = dict(row)
                    data["db"] = db_path
                    data["payload"] = _loads(data.get("payload_json"))
                    signals.append(data)
            if _has_table(conn, "forward_paper_positions"):
                where = "" if include_fixture else "WHERE fixture = 0"
                for row in conn.execute(f"SELECT * FROM forward_paper_positions {where}"):
                    data = dict(row)
                    positions[(str(data.get("signal_id")), str(data.get("token_id")))] = data
        finally:
            conn.close()
    return signals, positions


def _float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _edge_for_config(signal: dict[str, Any], *, annualized_vol: float) -> float | None:
    payload = signal.get("payload") or {}
    fv = payload.get("fair_value") if isinstance(payload.get("fair_value"), dict) else {}
    legacy_fv = payload.get("strike_fair_value") if isinstance(payload.get("strike_fair_value"), dict) else {}
    flat_fv = payload if payload.get("selected_edge") is not None else {}
    source = fv or legacy_fv or flat_fv
    market_type = payload.get("market_type") or legacy_fv.get("market_type")
    current_price = _float(payload.get("current_price") or source.get("current_price"))
    strike_price = _float(payload.get("strike_price") or source.get("strike_price"))
    seconds_to_expiry = _float(payload.get("seconds_to_expiry") or source.get("seconds_to_expiry"))
    selected_side = source.get("selected_side") or payload.get("outcome") or signal.get("outcome")
    executable_price = _float((payload.get("execution") or {}).get("avg_fill_price")) or _float(signal.get("avg_price")) or _float(signal.get("best_ask"))
    if current_price is None or strike_price is None or seconds_to_expiry is None or executable_price is None:
        persisted_edge = _float(source.get("selected_edge"))
        if persisted_edge is not None:
            return persisted_edge
        model_probability = _float(payload.get("model_probability_raw")) or _float(signal.get("model_probability"))
        if model_probability is not None and executable_price is not None:
            return model_probability - executable_price
        return None
    if market_type == "below_strike":
        fair = fair_value_below_strike(
            current_price=current_price,
            strike_price=strike_price,
            seconds_to_expiry=seconds_to_expiry,
            annualized_vol=annualized_vol,
        )
    else:
        fair = fair_value_above_strike(
            current_price=current_price,
            strike_price=strike_price,
            seconds_to_expiry=seconds_to_expiry,
            annualized_vol=annualized_vol,
        )
    probability = fair.probability_yes if selected_side == "YES" else 1.0 - fair.probability_yes
    return probability - executable_price


def _selected_by_config(signal: dict[str, Any], *, annualized_vol: float, min_edge: float, max_reprice_cents: float, market_score_min: float) -> bool:
    payload = signal.get("payload") or {}
    edge = _edge_for_config(signal, annualized_vol=annualized_vol)
    if edge is None or edge < min_edge:
        return False
    score = _float((payload.get("market_score") or {}).get("score"))
    if score is not None and score < market_score_min:
        return False
    stale = payload.get("stale_quote") if isinstance(payload.get("stale_quote"), dict) else {}
    change = _float(stale.get("bbo_change_cents"))
    if change is not None and change > max_reprice_cents:
        return False
    return True


def strike_shadow_calibration(
    db_paths: list[str | Path],
    *,
    include_fixture: bool = False,
    annualized_vol: list[float] | None = None,
    fair_value_min_edge: list[float] | None = None,
    stale_quote_max_reprice_cents: list[float] | None = None,
    market_score_min: list[float] | None = None,
) -> dict[str, Any]:
    signals, positions = _load_rows(db_paths, include_fixture=include_fixture)
    base_positions = [pos for pos in positions.values() if pos.get("status") == "closed"]
    base_result = {
        "signals": len(signals),
        "positions": len(positions),
        "closed_positions": len(base_positions),
        "net_pnl": sum(float(pos.get("net_pnl") or 0.0) for pos in base_positions),
    }

    vols = annualized_vol or [0.30, 0.45, 0.60, 0.90, 1.20]
    edges = fair_value_min_edge or [0.02, 0.03, 0.05, 0.08]
    reprices = stale_quote_max_reprice_cents or [0.5, 1.0, 2.0]
    scores = market_score_min or [0.70, 0.75, 0.85]
    rows: list[dict[str, Any]] = []
    for vol, edge, reprice, score_min in product(vols, edges, reprices, scores):
        selected = [
            signal
            for signal in signals
            if _selected_by_config(
                signal,
                annualized_vol=vol,
                min_edge=edge,
                max_reprice_cents=reprice,
                market_score_min=score_min,
            )
        ]
        selected_positions = [
            positions[(str(signal.get("signal_id")), str(signal.get("token_id")))]
            for signal in selected
            if (str(signal.get("signal_id")), str(signal.get("token_id"))) in positions
        ]
        closed = [pos for pos in selected_positions if pos.get("status") == "closed"]
        pnl = sum(float(pos.get("net_pnl") or 0.0) for pos in closed)
        warnings: list[str] = []
        if len(closed) < 5:
            warnings.extend(["small_sample", "do_not_promote"])
        if pnl > 0 and len(closed) <= 2:
            warnings.extend(["possible_overfit", "small_sample", "do_not_promote"])
        status = "negative"
        if pnl > 0:
            status = "positive_small_sample" if len(closed) < 20 else "positive_needs_more_evidence"
        elif pnl > base_result["net_pnl"]:
            status = "less_bad_not_positive"
        rows.append(
            {
                "annualized_vol": vol,
                "fair_value_min_edge": edge,
                "stale_quote_max_reprice_cents": reprice,
                "market_score_min": score_min,
                "signals": len(selected),
                "positions": len(selected_positions),
                "closed_positions": len(closed),
                "net_pnl": pnl,
                "status": status,
                "warnings": sorted(set(warnings)),
            }
        )
    rows.sort(key=lambda row: (float(row["net_pnl"]), int(row["closed_positions"])), reverse=True)
    diagnosis = []
    if base_result["net_pnl"] < 0:
        diagnosis.append("base model remains negative")
    if rows and rows[0]["net_pnl"] > base_result["net_pnl"]:
        diagnosis.append("stricter shadow filters reduce losses")
    if rows and int(rows[0]["closed_positions"]) < 5:
        diagnosis.append("best shadow config is too small to promote")
    return {
        "mode": "strike_shadow_calibration",
        "data_quality": "paper_live",
        "include_fixture": include_fixture,
        "base_result": base_result,
        "best_configs": rows[:10],
        "grid_count": len(rows),
        "diagnosis": diagnosis,
        "recommendation": "Do not trade. Use stricter v2 candidate config for future paper only.",
    }


def write_strike_shadow_calibration(result: dict[str, Any], output: str | Path) -> Path:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return path
