"""Journal facade."""

from __future__ import annotations

from typing import Any

from hermes_polymarket.storage.db import Database


class Journal:
    def __init__(self, db: Database):
        self.db = db

    def record(self, event_type: str, message: str, payload: dict[str, Any] | None = None) -> None:
        self.db.add_journal(event_type, message, payload or {})

