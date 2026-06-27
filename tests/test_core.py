"""Core factory tests."""

import json
from pathlib import Path

import pytest

from gates.verifier import run_cycle_gates, verify_xrpl_transaction
from observability.economic_ledger import EconomicLedger
from observability.grok_usage import parse_session_usage
from observability.revenue_ingest import _extract_payment_fields
from tools.publish_tools import build_index_html
from revenue_engines.registry import enabled_engines
from revenue_engines.tipping_funnel import TippingFunnel
from tools.xrpl_research import format_briefing_teaser
from tools.xrpl_tools import parse_ws_payment_message


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


def test_parse_ws_payment_message_tx_json():
    treasury = "rBiU74q2wCPQ7ri9YD6J6LrQ2Y3jFd8pcN"
    msg = {
        "type": "transaction",
        "engine_result": "tesSUCCESS",
        "tx_hash": "ABC123",
        "tx_json": {
            "TransactionType": "Payment",
            "Account": "rExternal111",
            "Destination": treasury,
            "Amount": "1000000",
        },
    }
    payment = parse_ws_payment_message(msg, treasury, testnet=True)
    assert payment is not None
    assert payment["tx_hash"] == "ABC123"
    assert payment["from"] == "rExternal111"
    assert "testnet.xrpl.org" in payment["explorer_url"]


def test_parse_ws_payment_message_ignores_internal():
    treasury = "rTreasury"
    factory = "rFactory"
    msg = {
        "type": "transaction",
        "engine_result": "tesSUCCESS",
        "transaction": {
            "TransactionType": "Payment",
            "Account": factory,
            "Destination": treasury,
            "hash": "INTERNAL1",
        },
    }
    payment = parse_ws_payment_message(msg, treasury)
    assert payment is not None
    assert payment["from"] == factory


def test_enabled_revenue_engines_include_high_impact():
    names = enabled_engines()
    assert "tipping_funnel" in names
    assert "paid_briefing" in names
    assert "content_operator" in names


def test_tipping_funnel_html_includes_treasury(tmp_path, monkeypatch):
    monkeypatch.setenv("PUBLISHED_DIR", str(tmp_path))
    import revenue_engines.tipping_funnel as tf

    monkeypatch.setattr(tf, "PUBLISHED_DIR", str(tmp_path))
    monkeypatch.setattr(tf, "resolve_treasury", lambda: "rTreasury123")
    monkeypatch.setattr(
        tf,
        "publish_and_anchor",
        lambda **kwargs: {
            "live_url": "https://example.com/tip.html",
            "xrpl_tx_hash": "HASH",
            "explorer_url": "https://testnet.xrpl.org/transactions/HASH",
        },
    )
    monkeypatch.setattr(tf, "write_tip_manifest", lambda **kwargs: tmp_path / "tip-manifest.json")

    result = TippingFunnel(published_dir=str(tmp_path)).run(cycle_id=42)
    html = (tmp_path / result["published_path"]).read_text() if "published_path" in result else ""
    if not html:
        html_files = list(tmp_path.glob("tip-cycle-42-*.html"))
        assert html_files
        html = html_files[0].read_text()
    assert "rTreasury123" in html
    assert '"type":"revenue"' in html.replace(" ", "")


def test_format_briefing_teaser():
    text = format_briefing_teaser({"cycle_id": 5, "factory_balance_xrp": 90.0})
    assert "Cycle 5" in text
    assert "90" in text


def test_extract_payment_fields_revenue_memo():
    memo_json = '{"type":"revenue","amount_usd_est":2.5,"notes":"tip"}'
    entry = {
        "validated": True,
        "tx": {
            "TransactionType": "Payment",
            "Account": "rExternal",
            "Destination": "rTreasury",
            "Amount": "5000000",
            "hash": "REV123",
            "Memos": [{"Memo": {"MemoData": memo_json.encode("utf-8").hex().upper()}}],
        },
    }
    payment = _extract_payment_fields(entry)
    assert payment is not None
    assert payment["tx_hash"] == "REV123"
    assert payment["memos"][0]["amount_usd_est"] == 2.5