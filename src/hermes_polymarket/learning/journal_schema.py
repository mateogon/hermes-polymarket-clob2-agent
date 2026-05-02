"""Structured learning records.

These records are intentionally plain dataclasses so they can be serialized to
SQLite JSON columns without coupling learning logic to a specific agent stack.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


MemoryType = Literal["episodic", "semantic", "procedural"]
ReflectionStatus = Literal["observation", "hypothesis", "candidate_rule", "promoted", "rejected", "retired"]
PromotionStatus = Literal["rejected", "paper_active", "retired"]


@dataclass(frozen=True)
class SerializableRecord:
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SignalDecisionRecord(SerializableRecord):
    signal_id: str
    strategy_id: str
    strategy_version: str
    config_hash: str
    code_commit_sha: str
    market_id: str
    outcome: str
    side: str
    risk_decision: str
    final_action: str
    human_reason: str
    condition_id: str | None = None
    token_id: str | None = None
    model_version: str | None = None
    prompt_version: str | None = None
    source_health: dict[str, Any] = field(default_factory=dict)
    market_snapshot: dict[str, Any] = field(default_factory=dict)
    model_probability_raw: float | None = None
    model_probability_adjusted: float | None = None
    confidence: float | None = None
    edge: float | None = None
    risk_reason: str | None = None


@dataclass(frozen=True)
class TradeLifecycleRecord(SerializableRecord):
    trade_id: str
    signal_id: str
    mode: str
    status: str
    entry_time: str | None = None
    entry_expected_price: float | None = None
    entry_fill_price: float | None = None
    entry_slippage: float | None = None
    exit_model: str | None = None
    exit_time: str | None = None
    exit_price: float | None = None
    exit_reason: str | None = None
    gross_pnl: float | None = None
    net_pnl: float | None = None
    max_adverse_excursion: float | None = None
    max_favorable_excursion: float | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CounterfactualRecord(SerializableRecord):
    counterfactual_id: str
    signal_id: str
    delay_seconds: int
    size_usd: float
    exit_model: str
    result: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ReflectionRecord(SerializableRecord):
    reflection_id: str
    trigger: str
    strategy_id: str
    observation: str
    likely_cause: str
    evidence_ids: tuple[str, ...]
    proposed_rule: str
    confidence: float
    status: ReflectionStatus = "observation"
    test_plan: str | None = None

    def __post_init__(self) -> None:
        if not self.evidence_ids:
            raise ValueError("ReflectionRecord requires evidence_ids")
        if not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be in [0, 1]")


@dataclass(frozen=True)
class HypothesisRecord(SerializableRecord):
    hypothesis_id: str
    statement: str
    status: ReflectionStatus
    evidence_ids: tuple[str, ...]
    proposed_test: dict[str, Any]
    result: dict[str, Any] = field(default_factory=dict)
    promoted_rule_id: str | None = None


@dataclass(frozen=True)
class StrategyExperimentRecord(SerializableRecord):
    run_id: str
    run_type: str
    strategy_id: str
    code_commit_sha: str
    config_hash: str
    data_quality: str
    parameters: dict[str, Any]
    metrics: dict[str, Any]
    artifacts: dict[str, Any] = field(default_factory=dict)
    dataset_version: str | None = None
    started_at: str | None = None
    ended_at: str | None = None

    def __post_init__(self) -> None:
        if not self.code_commit_sha:
            raise ValueError("code_commit_sha is required")
        if not self.config_hash:
            raise ValueError("config_hash is required")


@dataclass(frozen=True)
class PromotionDecisionRecord(SerializableRecord):
    rule_id: str
    status: PromotionStatus
    human_approved: bool
    active_in_paper: bool
    active_in_live: bool
    evidence_ids: tuple[str, ...]
    reason: str

    def __post_init__(self) -> None:
        if self.active_in_live:
            raise ValueError("Learning loop cannot activate rules in live mode")
        if self.status == "paper_active" and (not self.human_approved or not self.active_in_paper):
            raise ValueError("Paper promotion requires human approval and active_in_paper")
