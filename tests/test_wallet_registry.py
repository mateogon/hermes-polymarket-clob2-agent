from pathlib import Path

import pytest

from hermes_polymarket.data_sources.wallet_registry import WalletConfig, WalletRegistry


def test_wallet_registry_loads_signal_only_wallets(tmp_path: Path):
    path = tmp_path / "wallets.yaml"
    path.write_text(
        """
wallets:
  - name: test
    address: "0x55be7aa03ecfbe37aa5460db791205f7ac9ddca3"
    categories: ["crypto"]
"""
    )
    registry = WalletRegistry.load(path)
    wallet = registry.by_name("test")
    assert wallet.mode == "signal_only"
    assert wallet.min_trade_size_usd == 100.0
    assert wallet.categories == ("crypto",)
    assert registry.by_address("0x55BE7AA03ECFBE37AA5460DB791205F7AC9DDCA3") == wallet


def test_wallet_registry_rejects_non_signal_only_mode():
    with pytest.raises(ValueError, match="signal_only"):
        WalletConfig(
            name="bad",
            address="0x55be7aa03ecfbe37aa5460db791205f7ac9ddca3",
            mode="live_copy",
        )


def test_wallet_registry_rejects_invalid_address():
    with pytest.raises(ValueError, match="invalid wallet"):
        WalletConfig(name="bad", address="not-an-address")


def test_wallet_registry_rejects_duplicates():
    wallet = WalletConfig(name="a", address="0x55be7aa03ecfbe37aa5460db791205f7ac9ddca3")
    with pytest.raises(ValueError, match="duplicate"):
        WalletRegistry((wallet, wallet))
