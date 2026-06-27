"""Core factory tests."""

import json
from pathlib import Path

import pytest

from gates.verifier import run_cycle_gates, verify_xrpl_transaction
from observability.economic_ledger import EconomicLedger
from observability.grok_usage import parse_session_usage
from tools.publish_tools import build_index_html


def test_ledger_net_excludes_superseded(tmp_path):
    ledger_path = tmp_path / "ledger.jsonl"
    led = EconomicLedger(ledger_path=str(ledger_path))
    led.log_event("revenue", "old", 0.5, cycle_id=1, metadata={"superseded": True}, anchor_to_xrpl=False)
    led.log_event("cost", "grok", 1.0, cycle_id=1, anchor_to_xrpl=False)
    net = led.calculate_net()
    assert net["total_revenue_usd_est"] == 0.0
    assert net["total_cost_usd_est"] == 1.0


def test_build_index_html(tmp_path, monkeypatch):
    monkeypatch.setenv("PUBLISHED_DIR", str(tmp_path))
    import tools.publish_tools as pt

    monkeypatch.setattr(pt, "PUBLISHED_DIR", tmp_path)
    (tmp_path / "a.html").write_text("<html></html>")
    index = build_index_html(treasury_address="rTest123")
    assert index.exists()
    content = index.read_text()
    assert "a.html" in content
    assert "rTest123" in content


def test_run_cycle_gates_published_missing():
    result = run_cycle_gates(
        cycle_id=99,
        execution_result={"published_asset": "missing/file.html", "xrpl_tx_hash": "ABC"},
    )
    assert result["all_passed"] is False
    names = [g["gate"] for g in result["gates"]]
    assert "published_asset_exists" in names


def test_parse_session_usage_empty(tmp_path):
    parsed = parse_session_usage(tmp_path)
    assert parsed["turns"] == []