"""Configuration loading for the Hermes Polymarket agent."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import yaml
except Exception:  # pragma: no cover - only used if dependency is missing
    yaml = None


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    if yaml is None:
        raise RuntimeError("pyyaml is required to read config files")
    data = yaml.safe_load(path.read_text()) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config file must be a mapping: {path}")
    return data


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return float(value)


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return int(value)


@dataclass(frozen=True)
class Settings:
    polymarket_host: str
    polygon_chain_id: int
    mode: str
    database_path: Path
    initial_bankroll: float
    allow_live_trading: bool
    private_key: str
    funder: str
    builder_code: str

    kelly_fraction: float
    max_order_usd: float
    max_market_exposure_usd: float
    max_open_positions: int
    daily_loss_limit_usd: float
    max_portfolio_exposure_pct: float
    min_edge: float
    max_slippage: float
    min_orderbook_depth_usd: float
    min_hours_to_expiry: float
    confidence_discount: float
    reject_edge_over: float
    min_entry_price: float
    max_entry_price: float


def load_settings(config_dir: Path | None = None) -> Settings:
    config_dir = config_dir or PROJECT_ROOT / "config"
    default = _read_yaml(config_dir / "default.yaml")
    risk = _read_yaml(config_dir / "risk.yaml")

    db_path = Path(str(default.get("database_path", "data/hermes_polymarket.sqlite3")))
    if not db_path.is_absolute():
        db_path = PROJECT_ROOT / db_path

    return Settings(
        polymarket_host=os.getenv("POLYMARKET_HOST", str(default.get("polymarket_host", "https://clob.polymarket.com"))),
        polygon_chain_id=_env_int("POLYGON_CHAIN_ID", int(default.get("polygon_chain_id", 137))),
        mode=os.getenv("MODE", str(default.get("mode", "paper"))),
        database_path=db_path,
        initial_bankroll=_env_float("INITIAL_BANKROLL", float(default.get("initial_bankroll", 1000.0))),
        allow_live_trading=_env_bool("ALLOW_LIVE_TRADING", bool(default.get("allow_live_trading", False))),
        private_key=os.getenv("POLYMARKET_PRIVATE_KEY", ""),
        funder=os.getenv("POLYMARKET_FUNDER", ""),
        builder_code=os.getenv("POLY_BUILDER_CODE", ""),
        kelly_fraction=float(risk.get("kelly_fraction", 0.25)),
        max_order_usd=_env_float("MAX_ORDER_USD", float(risk.get("max_order_usd", 10.0))),
        max_market_exposure_usd=float(risk.get("max_market_exposure_usd", 25.0)),
        max_open_positions=int(risk.get("max_open_positions", 4)),
        daily_loss_limit_usd=_env_float("DAILY_LOSS_LIMIT_USD", float(risk.get("daily_loss_limit_usd", 30.0))),
        max_portfolio_exposure_pct=float(risk.get("max_portfolio_exposure_pct", 0.20)),
        min_edge=float(risk.get("min_edge", 0.03)),
        max_slippage=float(risk.get("max_slippage", 0.02)),
        min_orderbook_depth_usd=float(risk.get("min_orderbook_depth_usd", 25.0)),
        min_hours_to_expiry=float(risk.get("min_hours_to_expiry", 2.0)),
        confidence_discount=min(0.5, float(risk.get("confidence_discount", 0.5))),
        reject_edge_over=float(risk.get("reject_edge_over", 0.30)),
        min_entry_price=float(risk.get("min_entry_price", 0.03)),
        max_entry_price=float(risk.get("max_entry_price", 0.97)),
    )

