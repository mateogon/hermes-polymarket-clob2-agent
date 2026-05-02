import pytest

from hermes_polymarket.learning.memory_store import MemoryRecord, MemoryStore
from hermes_polymarket.learning.promotion import promote_candidate_to_paper, retire_rule
from hermes_polymarket.storage.db import Database


def test_promote_candidate_requires_paper_only_and_human_approval(tmp_path):
    db = Database(tmp_path / "learning.sqlite3")
    db.init_schema(1000)
    store = MemoryStore(db)
    store.put(MemoryRecord("rule_1", "semantic", "candidate_rule", {"rule_id": "rule_1"}, {"runs": ["r1"]}))
    with pytest.raises(ValueError, match="paper-only"):
        promote_candidate_to_paper(store, rule_id="rule_1", human_approved=True, paper_only=False, reason="bad")
    with pytest.raises(ValueError, match="human"):
        promote_candidate_to_paper(store, rule_id="rule_1", human_approved=False, paper_only=True, reason="bad")

    promoted = promote_candidate_to_paper(store, rule_id="rule_1", human_approved=True, paper_only=True, reason="ok")
    assert promoted.active_in_paper is True
    assert promoted.active_in_live is False
    assert store.search(memory_type="semantic")[0]["status"] == "paper_active"
    db.close()


def test_retire_rule_disables_paper_and_live(tmp_path):
    db = Database(tmp_path / "learning.sqlite3")
    db.init_schema(1000)
    store = MemoryStore(db)
    store.put(MemoryRecord("rule_1", "semantic", "paper_active", {"rule_id": "rule_1"}, {"runs": ["r1"]}, active_in_paper=True))
    retired = retire_rule(store, rule_id="rule_1", reason="bad forward paper")
    assert retired.status == "retired"
    assert retired.active_in_paper is False
    assert retired.active_in_live is False
    db.close()
