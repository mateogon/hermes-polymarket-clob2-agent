"""Wallet registry for signal-only public wallet-flow research."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from hermes_polymarket.config import PROJECT_ROOT


ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")


@dataclass(frozen=True)
class WalletConfig:
    name: str
    address: str
    mode: str = "signal_only"
    min_trade_size_usd: float = 100.0
    max_copy_delay_seconds: int = 20
    max_entry_worse_cents: float = 2.0
    categories: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("wallet name is required")
        if not ADDRESS_RE.match(self.address):
            raise ValueError(f"invalid wallet address: {self.address}")
        if self.mode != "signal_only":
            raise ValueError("wallet registry only supports signal_only mode")
        if self.min_trade_size_usd < 0:
            raise ValueError("min_trade_size_usd must be non-negative")
        if self.max_copy_delay_seconds <= 0:
            raise ValueError("max_copy_delay_seconds must be positive")
        if self.max_entry_worse_cents < 0:
            raise ValueError("max_entry_worse_cents must be non-negative")


def _wallet(raw: dict[str, Any]) -> WalletConfig:
    return WalletConfig(
        name=str(raw.get("name") or ""),
        address=str(raw.get("address") or ""),
        mode=str(raw.get("mode") or "signal_only"),
        min_trade_size_usd=float(raw.get("min_trade_size_usd", 100.0)),
        max_copy_delay_seconds=int(raw.get("max_copy_delay_seconds", 20)),
        max_entry_worse_cents=float(raw.get("max_entry_worse_cents", 2.0)),
        categories=tuple(str(item) for item in raw.get("categories", []) if item),
    )


class WalletRegistry:
    def __init__(self, wallets: tuple[WalletConfig, ...]):
        self.wallets = wallets
        lower = [wallet.address.lower() for wallet in wallets]
        if len(lower) != len(set(lower)):
            raise ValueError("duplicate wallet address in registry")

    @classmethod
    def load(cls, path: Path | None = None) -> "WalletRegistry":
        path = path or PROJECT_ROOT / "config" / "wallets.yaml"
        data = yaml.safe_load(path.read_text()) or {}
        raw_wallets = data.get("wallets") or []
        if not isinstance(raw_wallets, list):
            raise ValueError("wallets.yaml must contain a wallets list")
        return cls(tuple(_wallet(item) for item in raw_wallets if isinstance(item, dict)))

    def by_name(self, name: str) -> WalletConfig:
        for wallet in self.wallets:
            if wallet.name == name:
                return wallet
        raise KeyError(name)

    def by_address(self, address: str) -> WalletConfig:
        wanted = address.lower()
        for wallet in self.wallets:
            if wallet.address.lower() == wanted:
                return wallet
        raise KeyError(address)

