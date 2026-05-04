"""File-backed research data cache.

The cache is intentionally simple: JSON/JSONL files plus manifests. It is for
paper/research backtests only and carries provenance with every fetch.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Iterable

from hermes_polymarket.config import PROJECT_ROOT
from hermes_polymarket.data_sources.binance_historical import BinanceCandle
from hermes_polymarket.data_sources.polymarket_data_api import WalletTrade, parse_wallet_trade


DATA_QUALITY = "research_cache_public_historical"


def default_research_cache_root() -> Path:
    raw = os.getenv("HERMES_RESEARCH_CACHE_DIR")
    root = Path(raw) if raw else PROJECT_ROOT / "data/research_cache"
    return root if root.is_absolute() else PROJECT_ROOT / root


class ResearchDataCache:
    def __init__(self, root: Path | None = None):
        self.root = root or default_research_cache_root()

    def write_gamma_universe(self, *, label: str, events: list[dict[str, Any]], markets: list[dict[str, Any]], params: dict[str, Any]) -> dict[str, Any]:
        path = self.root / "gamma_universe" / f"{_safe(label)}.json"
        payload = {
            "data_quality": DATA_QUALITY,
            "source": "gamma",
            "kind": "gamma_universe",
            "params": params,
            "events": events,
            "markets": markets,
        }
        _write_json(path, payload)
        return self._manifest(path, kind="gamma_universe", source="gamma", params=params, rows=len(events) + len(markets))

    def write_gamma_market(self, *, slug: str, markets: list[dict[str, Any]], params: dict[str, Any]) -> dict[str, Any]:
        path = self.root / "gamma_markets" / f"{_safe(slug)}.json"
        payload = {
            "data_quality": DATA_QUALITY,
            "source": "gamma",
            "kind": "gamma_market",
            "slug": slug,
            "params": params,
            "markets": markets,
        }
        _write_json(path, payload)
        return self._manifest(path, kind="gamma_market", source="gamma", params=params, rows=len(markets))

    def write_polymarket_trades(self, *, condition_id: str, trades: list[WalletTrade], params: dict[str, Any]) -> dict[str, Any]:
        path = self.trades_path(condition_id)
        rows = [trade.raw for trade in trades]
        _write_jsonl(path, rows)
        manifest = self._manifest(path, kind="polymarket_trades", source="polymarket_data_api", params=params, rows=len(rows))
        _write_json(path.with_suffix(".manifest.json"), manifest)
        return manifest

    def write_binance_klines(
        self,
        *,
        symbol: str,
        interval: str,
        start_ts_ms: int,
        end_ts_ms: int,
        candles: list[BinanceCandle],
        params: dict[str, Any],
    ) -> dict[str, Any]:
        path = self.klines_path(symbol=symbol, interval=interval, start_ts_ms=start_ts_ms, end_ts_ms=end_ts_ms)
        _write_jsonl(path, [_to_dict(candle) for candle in candles])
        manifest = self._manifest(path, kind="binance_klines", source="binance_rest", params=params, rows=len(candles))
        _write_json(path.with_suffix(".manifest.json"), manifest)
        return manifest

    def load_polymarket_trades(self, *, condition_id: str) -> list[WalletTrade]:
        trades: list[WalletTrade] = []
        for row in _read_jsonl(self.trades_path(condition_id)):
            trade = parse_wallet_trade(row)
            if trade is not None:
                trades.append(trade)
        return trades

    def load_binance_klines(self, *, symbol: str, interval: str, start_ts_ms: int, end_ts_ms: int) -> list[dict[str, Any]]:
        return _read_jsonl(self.klines_path(symbol=symbol, interval=interval, start_ts_ms=start_ts_ms, end_ts_ms=end_ts_ms))

    def trades_path(self, condition_id: str) -> Path:
        return self.root / "polymarket_trades" / f"{_safe(condition_id)}.jsonl"

    def klines_path(self, *, symbol: str, interval: str, start_ts_ms: int, end_ts_ms: int) -> Path:
        return self.root / "binance_klines" / f"{_safe(symbol.lower())}_{_safe(interval)}_{start_ts_ms}_{end_ts_ms}.jsonl"

    def status(self) -> dict[str, Any]:
        groups = {
            "gamma_universe": list((self.root / "gamma_universe").glob("*.json")),
            "gamma_markets": list((self.root / "gamma_markets").glob("*.json")),
            "polymarket_trades": list((self.root / "polymarket_trades").glob("*.jsonl")),
            "binance_klines": list((self.root / "binance_klines").glob("*.jsonl")),
        }
        return {
            "data_quality": DATA_QUALITY,
            "root": str(self.root),
            "groups": {
                key: {
                    "files": len(paths),
                    "bytes": sum(path.stat().st_size for path in paths if path.exists()),
                }
                for key, paths in groups.items()
            },
        }

    def _manifest(self, path: Path, *, kind: str, source: str, params: dict[str, Any], rows: int) -> dict[str, Any]:
        return {
            "data_quality": DATA_QUALITY,
            "kind": kind,
            "source": source,
            "path": str(path),
            "rows": rows,
            "params": params,
        }


def _safe(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in str(value)).strip("_") or "unknown"


def _to_dict(value: Any) -> dict[str, Any]:
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return dict(value)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text().splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out
