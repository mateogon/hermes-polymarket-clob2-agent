"""Safe paper scan placeholder."""

from __future__ import annotations

from hermes_polymarket.config import Settings, load_settings
from hermes_polymarket.storage.db import Database


def run_paper_scan(settings: Settings | None = None) -> dict:
    settings = settings or load_settings()
    db = Database(settings.database_path)
    db.init_schema(settings.initial_bankroll)
    try:
        account = db.account()
        return {
            "mode": "paper",
            "cash": float(account["cash"]),
            "open_positions": len(db.open_positions()),
            "status": "ready",
        }
    finally:
        db.close()


if __name__ == "__main__":
    print(run_paper_scan())

