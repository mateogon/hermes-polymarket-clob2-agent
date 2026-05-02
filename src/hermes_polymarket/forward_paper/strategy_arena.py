"""Diagnostic paper strategy arena.

The arena compares stored forward-paper observations. It does not generate
signals, simulate new fills, or place orders.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


DEFAULT_CONFIG_PATH = Path("config/strategy_arena.yaml")


@dataclass(frozen=True)
class ArenaDataset:
    runs: list[dict[str, Any]]
    signals: list[dict[str, Any]]
    positions: list[dict[str, Any]]


def load_arena_config(path: str | Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    config_path = Path(path)
    if not config_path.exists():
        return {
            "arena": {
                "mode": "diagnostic_paper",
                "baseline": "no_trade",
                "artifact_dir": "artifacts/strategy_arena",
                "min_signals_for_claim": 50,
                "min_closed_positions_for_claim": 20,
                "exclude_fixture_by_default": True,
            },
            "strategies": [{"id": "no_trade", "type": "baseline", "label": "baseline"}],
        }
    loaded = yaml.safe_load(config_path.read_text()) or {}
    return loaded if isinstance(loaded, dict) else {}


def _connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _loads(value: Any, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _threshold(run: dict[str, Any]) -> float | None:
    config = _loads(run.get("config_json"), {})
    try:
        value = config.get("min_move_pct")
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def load_arena_dataset(db_paths: list[str | Path], *, include_fixture: bool = False) -> ArenaDataset:
    runs: list[dict[str, Any]] = []
    signals: list[dict[str, Any]] = []
    positions: list[dict[str, Any]] = []

    for raw_path in db_paths:
        db_path = str(raw_path)
        conn = _connect(db_path)
        try:
            fixture_clause = "" if include_fixture else "WHERE fixture = 0"
            run_rows = [dict(row) | {"db": db_path} for row in conn.execute(f"SELECT * FROM forward_paper_runs {fixture_clause}")]
            runs.extend(run_rows)
            run_thresholds = {row["run_id"]: _threshold(row) for row in run_rows}

            signal_where = "" if include_fixture else "WHERE fixture = 0"
            for row in conn.execute(f"SELECT * FROM forward_paper_signals {signal_where}"):
                data = dict(row)
                data["db"] = db_path
                data["threshold"] = run_thresholds.get(data["run_id"])
                data["payload"] = _loads(data.get("payload_json"), {})
                signals.append(data)

            position_where = "" if include_fixture else "WHERE fixture = 0"
            for row in conn.execute(f"SELECT * FROM forward_paper_positions {position_where}"):
                data = dict(row)
                data["db"] = db_path
                data["threshold"] = run_thresholds.get(data["run_id"])
                data["payload"] = _loads(data.get("payload_json"), {})
                positions.append(data)
        finally:
            conn.close()

    return ArenaDataset(runs=runs, signals=signals, positions=positions)


def _matches_strategy(row: dict[str, Any], strategy: dict[str, Any]) -> bool:
    strategy_type = strategy.get("type")
    if strategy_type == "baseline":
        return False
    if strategy_type == "threshold_filter":
        threshold = row.get("threshold")
        target = strategy.get("min_move_pct")
        return threshold is not None and target is not None and abs(float(threshold) - float(target)) < 1e-9
    if strategy_type == "symbol_filter":
        return str(row.get("symbol") or "").lower() in {str(symbol).lower() for symbol in strategy.get("symbols", [])}
    if strategy_type == "reject_reason_analysis":
        text = f"{row.get('final_action')}:{row.get('risk_reason')}".lower()
        return any(str(reason).lower() in text for reason in strategy.get("reject_reasons", []))
    if strategy_type == "shadow_only":
        payload = row.get("payload") or {}
        shadow = payload.get("shadow_risk") if isinstance(payload, dict) else None
        if not isinstance(shadow, dict):
            return False
        max_slippage = strategy.get("max_slippage")
        return any(f"max_slippage={max_slippage}" in key and value == "allowed_shadow_only" for key, value in shadow.items())
    return False


def _drawdown(pnls: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return max_dd


def _profit_factor(pnls: list[float]) -> float | None:
    gains = sum(value for value in pnls if value > 0)
    losses = abs(sum(value for value in pnls if value < 0))
    if losses == 0:
        return None
    return gains / losses


def _warnings(
    *,
    strategy: dict[str, Any],
    signals: list[dict[str, Any]],
    positions: list[dict[str, Any]],
    pnls: list[float],
    top_rejects: dict[str, int],
    min_signals_for_claim: int,
    min_closed_positions_for_claim: int,
) -> list[str]:
    warnings: list[str] = []
    if not signals:
        warnings.append("no_signals")
    if not pnls:
        warnings.append("no_closed_positions")
    if len(signals) < min_signals_for_claim:
        warnings.append("small_sample")
    if len(pnls) <= 1 and pnls:
        warnings.append("very_small_sample")
        warnings.append("possible_one_trade_effect")
    if strategy.get("label") == "exploratory":
        warnings.append("exploratory_threshold")
    if len(pnls) < min_closed_positions_for_claim:
        warnings.append("not_strategy_claim")
    dominant = next(iter(top_rejects), "")
    if dominant and ("market_quality" in dominant or "thin_depth" in dominant or "wide_spread" in dominant):
        warnings.append("dominant_reject_market_quality")
    if dominant and ("min_liquidity" in dominant or "max_slippage" in dominant):
        warnings.append("dominant_reject_liquidity")
    warnings.append("not_live_ready")
    return list(dict.fromkeys(warnings))


def evaluate_strategy(
    strategy: dict[str, Any],
    dataset: ArenaDataset,
    *,
    min_signals_for_claim: int,
    min_closed_positions_for_claim: int,
) -> dict[str, Any]:
    if strategy.get("type") == "baseline":
        return {
            "strategy_id": strategy["id"],
            "type": "baseline",
            "label": strategy.get("label"),
            "signals": 0,
            "paper_opportunities": 0,
            "positions": 0,
            "closed_positions": 0,
            "open_positions": 0,
            "net_pnl": 0.0,
            "avg_pnl_per_position": 0.0,
            "win_rate": 0.0,
            "max_drawdown": 0.0,
            "profit_factor": None,
            "top_reject_reasons": {},
            "dominant_symbol": None,
            "dominant_threshold": None,
            "warnings": ["baseline", "not_strategy_claim", "not_live_ready"],
        }

    signals = [row for row in dataset.signals if _matches_strategy(row, strategy)]
    run_ids = {row["run_id"] for row in signals}
    if strategy.get("type") == "threshold_filter":
        positions = [row for row in dataset.positions if row["run_id"] in run_ids]
    elif strategy.get("type") == "symbol_filter":
        positions = [row for row in dataset.positions if _matches_strategy(row, strategy)]
    else:
        positions = []
    closed = [row for row in positions if row.get("status") == "closed"]
    open_positions = [row for row in positions if row.get("status") == "open"]
    pnls = [float(row.get("net_pnl") or 0.0) for row in closed]
    rejects = Counter(f"{row.get('final_action')}:{row.get('risk_reason')}" for row in signals if row.get("final_action") != "paper_fill")
    symbols = Counter(str(row.get("symbol") or "unknown") for row in signals)
    thresholds = Counter(str(row.get("threshold") if row.get("threshold") is not None else "unknown") for row in signals)
    top_rejects = {key: value for key, value in rejects.most_common(10)}

    return {
        "strategy_id": strategy["id"],
        "type": strategy.get("type"),
        "label": strategy.get("label"),
        "signals": len(signals),
        "paper_opportunities": sum(1 for row in signals if row.get("fill_status") == "filled"),
        "positions": len(positions),
        "closed_positions": len(closed),
        "open_positions": len(open_positions),
        "net_pnl": sum(pnls),
        "avg_pnl_per_position": sum(pnls) / len(pnls) if pnls else 0.0,
        "win_rate": sum(1 for value in pnls if value > 0) / len(pnls) if pnls else 0.0,
        "max_drawdown": _drawdown(pnls),
        "profit_factor": _profit_factor(pnls),
        "top_reject_reasons": top_rejects,
        "dominant_symbol": symbols.most_common(1)[0][0] if symbols else None,
        "dominant_threshold": thresholds.most_common(1)[0][0] if thresholds else None,
        "warnings": _warnings(
            strategy=strategy,
            signals=signals,
            positions=positions,
            pnls=pnls,
            top_rejects=top_rejects,
            min_signals_for_claim=min_signals_for_claim,
            min_closed_positions_for_claim=min_closed_positions_for_claim,
        ),
    }


def run_strategy_arena(
    db_paths: list[str | Path],
    *,
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    include_fixture: bool = False,
) -> dict[str, Any]:
    config = load_arena_config(config_path)
    arena_config = config.get("arena", {})
    strategies = config.get("strategies", [])
    dataset = load_arena_dataset(db_paths, include_fixture=include_fixture)
    min_signals_for_claim = int(arena_config.get("min_signals_for_claim", 50))
    min_closed_positions_for_claim = int(arena_config.get("min_closed_positions_for_claim", 20))
    evaluated = [
        evaluate_strategy(
            strategy,
            dataset,
            min_signals_for_claim=min_signals_for_claim,
            min_closed_positions_for_claim=min_closed_positions_for_claim,
        )
        for strategy in strategies
    ]
    closed_positions = [row for row in dataset.positions if row.get("status") == "closed"]
    total_pnl = sum(float(row.get("net_pnl") or 0.0) for row in closed_positions)
    ready_for_strategy_claim = (
        len(dataset.signals) >= min_signals_for_claim
        and len(closed_positions) >= min_closed_positions_for_claim
        and total_pnl > 0
    )
    return {
        "mode": "diagnostic_paper",
        "data_quality": "paper_live",
        "baseline": arena_config.get("baseline", "no_trade"),
        "include_fixture": include_fixture,
        "ready_for_strategy_claim": ready_for_strategy_claim,
        "ready_for_live_review": False,
        "dbs": [str(path) for path in db_paths],
        "strategies": evaluated,
        "symbol_summary": symbol_summary(dataset),
        "conclusion": "Diagnostic only. More forward data required before any strategy claim or live review.",
    }


def symbol_summary(dataset: ArenaDataset) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for symbol in sorted({str(row.get("symbol") or "unknown") for row in dataset.signals + dataset.positions}):
        signals = [row for row in dataset.signals if str(row.get("symbol") or "unknown") == symbol]
        positions = [row for row in dataset.positions if str(row.get("symbol") or "unknown") == symbol]
        closed = [row for row in positions if row.get("status") == "closed"]
        pnl = sum(float(row.get("net_pnl") or 0.0) for row in closed)
        rejects = Counter(f"{row.get('final_action')}:{row.get('risk_reason')}" for row in signals if row.get("final_action") != "paper_fill")
        warning = "needs more sample"
        if rejects and any("thin_depth" in key or "wide_spread" in key for key, _ in rejects.most_common(1)):
            warning = "market quality rejects dominate"
        out[symbol] = {
            "signals": len(signals),
            "positions": len(positions),
            "closed": len(closed),
            "net_pnl": pnl,
            "top_reject": rejects.most_common(1)[0][0] if rejects else None,
            "warning": warning,
        }
    return out


def write_arena_artifact(result: dict[str, Any], *, output: str | Path | None = None, artifact_dir: str | Path = "artifacts/strategy_arena") -> Path:
    path = Path(output) if output else Path(artifact_dir) / "latest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return path


def load_arena_artifact(path: str | Path = "artifacts/strategy_arena/latest.json") -> dict[str, Any]:
    return json.loads(Path(path).read_text())
