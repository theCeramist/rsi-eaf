"""XRPL dual-network unit tests (no live mainnet spend)."""

from __future__ import annotations

import json
from pathlib import Path

import factory_core.xrpl_network as xn


def test_ops_defaults_testnet(monkeypatch):
    monkeypatch.delenv("XRPL_NETWORK", raising=False)
    monkeypatch.delenv("FACTORY_MAINNET_TREASURY_ADDRESS", raising=False)
    monkeypatch.delenv("MAINNET_TREASURY_ADDRESS", raising=False)
    monkeypatch.delenv("XRPL_OPS_NETWORK", raising=False)
    assert xn.ops_network() == "testnet"
    assert xn.network_mode() == "testnet"


def test_dual_when_mainnet_treasury(monkeypatch):
    monkeypatch.setenv("FACTORY_MAINNET_TREASURY_ADDRESS", "rMainnetTreasuryAddressTest0001")
    monkeypatch.setenv("FACTORY_TREASURY_ADDRESS", "rTestnetTreasuryAddress000000001")
    monkeypatch.delenv("XRPL_NETWORK", raising=False)
    monkeypatch.setenv("XRPL_PREFER_MAINNET_REVENUE", "true")
    # Invalid classic addr still counts as configured string for mode; readiness regex may fail
    monkeypatch.setenv(
        "FACTORY_MAINNET_TREASURY_ADDRESS",
        "rPT1Sjq2YGrBMTttX4GZHjKu9dyfzbpAYe",
    )
    assert xn.network_mode() == "dual"
    addr, net = xn.resolve_public_treasury()
    assert net == "mainnet"
    assert addr.startswith("r")


def test_mainnet_outbound_blocked_by_default(monkeypatch):
    monkeypatch.delenv("MAINNET_OUTBOUND_ENABLED", raising=False)
    gate = xn.mainnet_outbound_allowed(0.01)
    assert gate["allowed"] is False


def test_mainnet_outbound_cap(monkeypatch):
    monkeypatch.setenv("MAINNET_OUTBOUND_ENABLED", "true")
    monkeypatch.setenv("MAINNET_MAX_OUTBOUND_XRP", "0.05")
    assert xn.mainnet_outbound_allowed(0.01)["allowed"] is True
    assert xn.mainnet_outbound_allowed(1.0)["allowed"] is False


def test_write_readiness_artifacts(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FACTORY_MAINNET_TREASURY_ADDRESS", "rPT1Sjq2YGrBMTttX4GZHjKu9dyfzbpAYe")
    monkeypatch.setenv("FACTORY_TREASURY_ADDRESS", "rBiU74q2wCPQ7ri9YD6J6LrQ2Y3jFd8pcN")
    monkeypatch.setenv("XRPL_NETWORK", "dual")
    monkeypatch.setenv("XRPL_REVENUE_NETWORK", "mainnet")
    monkeypatch.setenv("MAINNET_OUTBOUND_ENABLED", "false")
    # Avoid live RPC flakiness
    monkeypatch.setattr(
        xn,
        "is_mainnet_revenue_ready",
        lambda strict=True: {
            "ready": not strict,
            "strict": strict,
            "checks": {
                "mainnet_treasury_configured": True,
                "account_activated": False,
                "rpc_mainnet_reachable": True,
                "outbound_disabled_by_default": True,
            },
        },
    )
    out = xn.write_readiness_artifacts(1)
    assert Path("published/network-status.json").is_file()
    assert Path("observability/mainnet_readiness.json").is_file()
    public = json.loads(Path("published/network-status.json").read_text(encoding="utf-8"))
    assert public["revenue_network"] == "mainnet"
    assert out["public_network"] == "mainnet"
