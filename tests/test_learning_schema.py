import pytest

from hermes_polymarket.learning.journal_schema import (
    PromotionDecisionRecord,
    ReflectionRecord,
    StrategyExperimentRecord,
)


def test_reflection_requires_evidence_ids():
    with pytest.raises(ValueError, match="evidence"):
        ReflectionRecord(
            reflection_id="r1",
            trigger="losing_trade",
            strategy_id="s",
            observation="obs",
            likely_cause="cause",
            evidence_ids=(),
            proposed_rule="rule",
            confidence=0.5,
        )


def test_experiment_requires_hashes():
    with pytest.raises(ValueError, match="code_commit_sha"):
        StrategyExperimentRecord("run", "replay", "s", "", "cfg", "historical_approx", {}, {})


def test_candidate_rule_cannot_become_live_active():
    with pytest.raises(ValueError, match="live"):
        PromotionDecisionRecord(
            rule_id="rule",
            status="paper_active",
            human_approved=True,
            active_in_paper=True,
            active_in_live=True,
            evidence_ids=("run",),
            reason="bad",
        )


def test_paper_promotion_requires_human_approval():
    with pytest.raises(ValueError, match="human"):
        PromotionDecisionRecord(
            rule_id="rule",
            status="paper_active",
            human_approved=False,
            active_in_paper=True,
            active_in_live=False,
            evidence_ids=("run",),
            reason="missing approval",
        )
