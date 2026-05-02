"""Paper-only promotion helpers."""

from __future__ import annotations

from hermes_polymarket.learning.memory_store import MemoryRecord, MemoryStore


def promote_candidate_to_paper(
    store: MemoryStore,
    *,
    rule_id: str,
    human_approved: bool,
    paper_only: bool,
    reason: str,
) -> MemoryRecord:
    if not paper_only:
        raise ValueError("Promotion requires --paper-only")
    if not human_approved:
        raise ValueError("Promotion requires human approval")
    rows = store.search(query=rule_id, limit=1)
    if not rows:
        raise KeyError(rule_id)
    row = rows[0]
    record = MemoryRecord(
        memory_id=row["memory_id"],
        memory_type=row["memory_type"],
        status="paper_active",
        strategy_id=row["strategy_id"],
        wallet=row["wallet"],
        market_category=row["market_category"],
        content={"promoted_rule_id": rule_id, "reason": reason, "previous": row["content_json"]},
        evidence={"previous": row["evidence_json"]},
        confidence=float(row["confidence"]),
        active_in_paper=True,
        active_in_live=False,
    )
    store.put(record)
    return record


def retire_rule(store: MemoryStore, *, rule_id: str, reason: str) -> MemoryRecord:
    rows = store.search(query=rule_id, limit=1)
    if not rows:
        raise KeyError(rule_id)
    row = rows[0]
    record = MemoryRecord(
        memory_id=row["memory_id"],
        memory_type=row["memory_type"],
        status="retired",
        strategy_id=row["strategy_id"],
        wallet=row["wallet"],
        market_category=row["market_category"],
        content={"retired_rule_id": rule_id, "reason": reason, "previous": row["content_json"]},
        evidence={"previous": row["evidence_json"]},
        confidence=float(row["confidence"]),
        active_in_paper=False,
        active_in_live=False,
    )
    store.put(record)
    return record
