"""Artifact writer for forward paper runs."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("empty\n")
        return
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_forward_paper_artifacts(
    *,
    root: Path,
    run_id: str,
    summary: dict[str, Any],
    report: dict[str, Any],
    signals: list[dict[str, Any]],
    positions: list[dict[str, Any]],
    quality: dict[str, Any],
) -> dict[str, str]:
    root.mkdir(parents=True, exist_ok=True)
    paths = {
        "manifest": root / "manifest.json",
        "summary": root / "summary.json",
        "report": root / "report.json",
        "signals_csv": root / "signals.csv",
        "positions_csv": root / "positions.csv",
        "quality": root / "quality.json",
        "notes": root / "notes.md",
    }
    paths["manifest"].write_text(
        json.dumps(
            {
                "run_id": run_id,
                "data_quality": "paper_live",
                "mode": "forward_paper_only",
                "paths": {key: str(value) for key, value in paths.items()},
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    paths["summary"].write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    paths["report"].write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    paths["quality"].write_text(json.dumps(quality, indent=2, sort_keys=True) + "\n")
    _write_csv(paths["signals_csv"], signals)
    _write_csv(paths["positions_csv"], positions)
    paths["notes"].write_text(
        "# Forward Paper Notes\n\n"
        "- This is paper-only.\n"
        "- No live orders were placed.\n"
        "- Exploratory thresholds are not strategy thresholds.\n"
    )
    return {key: str(value) for key, value in paths.items()}
