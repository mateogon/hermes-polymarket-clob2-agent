import json

from hermes_polymarket.learning.decision_journal import DecisionJournal
from hermes_polymarket.learning.journal_schema import HypothesisRecord, SignalDecisionRecord, TradeLifecycleRecord
from hermes_polymarket.learning.memory_store import MemoryRecord, MemoryStore
from hermes_polymarket.storage.db import Database


def test_decision_journal_roundtrip(tmp_path):
    db = Database(tmp_path / "learning.sqlite3")
    db.init_schema(1000)
    journal = DecisionJournal(db)
    record = SignalDecisionRecord(
        signal_id="sig1",
        strategy_id="wallet_flow",
        strategy_version="v1",
        config_hash="cfg",
        code_commit_sha="sha",
        market_id="m",
        outcome="YES",
        side="buy",
        risk_decision="reject",
        final_action="reject",
        human_reason="test",
        market_snapshot={"best_ask": 0.5},
    )
    journal.record_signal_decision(record)
    row = journal.get_signal_decision("sig1")
    assert row["strategy_id"] == "wallet_flow"
    assert json.loads(row["market_snapshot_json"])["best_ask"] == 0.5
    db.close()


def test_trade_lifecycle_and_hypothesis_roundtrip(tmp_path):
    db = Database(tmp_path / "learning.sqlite3")
    db.init_schema(1000)
    journal = DecisionJournal(db)
    journal.record_trade_lifecycle(TradeLifecycleRecord("t1", "sig1", "paper", "closed", net_pnl=1.2))
    journal.record_hypothesis(HypothesisRecord("h1", "delay kills edge", "hypothesis", ("sig1",), {"replay": True}))
    assert db.conn.execute("SELECT net_pnl FROM trade_lifecycle WHERE trade_id = 't1'").fetchone()["net_pnl"] == 1.2
    assert journal.hypotheses()[0]["hypothesis_id"] == "h1"
    db.close()


def test_memory_store_separates_memory_types_and_searches(tmp_path):
    db = Database(tmp_path / "learning.sqlite3")
    db.init_schema(1000)
    store = MemoryStore(db)
    store.put(MemoryRecord("e1", "episodic", "candidate", {"lesson": "coinman2 delay"}, {"signals": ["s1"]}, wallet="coinman2"))
    store.put(MemoryRecord("s1", "semantic", "candidate", {"rule": "delay <= 10"}, {"runs": ["r1"]}, strategy_id="wallet_flow"))
    store.put(MemoryRecord("p1", "procedural", "paper_active", {"playbook": "paper only"}, {"approval": True}, active_in_paper=True))
    assert len(store.search(memory_type="episodic")) == 1
    assert len(store.search(query="coinman2")) == 1
    assert len(store.search(memory_type="procedural")) == 1
    db.close()
