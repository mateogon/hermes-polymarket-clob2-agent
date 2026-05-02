"""Dry-run execution: validate but never sign or post."""

from __future__ import annotations

from hermes_polymarket.execution.order_validator import OrderValidator, ValidationResult
from hermes_polymarket.polymarket.types import MarketMetadata, OrderBook, TradeProposal
from hermes_polymarket.risk.exposure import ExposureSnapshot


class DryRunExecutor:
    def __init__(self, validator: OrderValidator):
        self.validator = validator

    def run(self, proposal: TradeProposal, metadata: MarketMetadata, book: OrderBook, exposure: ExposureSnapshot) -> ValidationResult:
        return self.validator.validate(proposal, metadata, book, exposure)

