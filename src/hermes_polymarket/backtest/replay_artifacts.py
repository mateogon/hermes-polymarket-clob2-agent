"""Artifact writers for replay runs."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from hermes_polymarket.backtest.wallet_replay_models import ReplayTradeResult


def write_replay_artifacts_csv(
    *,
    root: Path,
    run_id: str,
    summary: dict[str, Any],
    results: list[ReplayTradeResult],
    config: dict[str, Any],
    quality: dict[str, Any],
    code_commit_sha: str,
    config_hash: str,
) -> dict[str, str]:
    root.mkdir(parents=True, exist_ok=True)

    paths = {
        "manifest": root / "manifest.json",
        "summary": root / "summary.json",
        "replay_trades_csv": root / "replay_trades.csv",
        "by_delay_csv": root / "by_delay.csv",
        "skipped_by_reason_csv": root / "skipped_by_reason.csv",
        "pnl_by_category_csv": root / "pnl_by_category.csv",
    }

    manifest = {
        "run_id": run_id,
        "code_commit_sha": code_commit_sha,
        "config_hash": config_hash,
        "data_quality": summary.get("data_quality"),
        "paths": {key: str(path) for key, path in paths.items()},
        "config": config,
        "quality": quality,
    }

    paths["manifest"].write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    paths["summary"].write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")

    with paths["replay_trades_csv"].open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "replay_trade_id",
                "run_id",
                "wallet",
                "condition_id",
                "asset_id",
                "outcome",
                "delay_seconds",
                "status",
                "entry_time",
                "entry_price",
                "leader_entry_price",
                "exit_time",
                "exit_price",
                "exit_model",
                "pnl",
                "roi",
                "worse_entry_cents",
                "skipped_reason",
                "category",
            ],
        )
        writer.writeheader()
        for result in results:
            row = result.to_storage_dict()
            row.pop("payload_json", None)
            writer.writerow(row)

    with paths["by_delay_csv"].open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["delay", "observed", "replayed", "skipped", "pending", "roi", "win_rate", "max_drawdown", "average_worse_entry_cents"],
        )
        writer.writeheader()
        for delay, payload in summary.get("by_delay", {}).items():
            writer.writerow({"delay": delay, **payload})

    with paths["skipped_by_reason_csv"].open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["reason", "count"])
        writer.writeheader()
        for reason, count in summary.get("skipped_trades_by_reason", {}).items():
            writer.writerow({"reason": reason, "count": count})

    with paths["pnl_by_category_csv"].open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["category", "pnl"])
        writer.writeheader()
        for category, pnl in summary.get("pnl_by_category", {}).items():
            writer.writerow({"category": category, "pnl": pnl})

    return {key: str(path) for key, path in paths.items()}
