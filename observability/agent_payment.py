"""
Agent-native payment surface — one JSON file for any agent to pay the factory treasury.

Designed for: Grok agents, MCP wallets, ACP lanes, X402-style clients (future).
Humans can still use Destination Tag 1 only (no memo required).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from observability.payment_intent import (
    BRIEFING_TAG,
    BRIEFING_USD,
    MYTHOS_TAG,
    MYTHOS_USD,
    SERVICE_TAG,
    SERVICE_USD,
    TIP_TAG,
    TIP_USD,
    TOOL_TAG,
    TOOL_USD,
)

PUBLISHED_DIR = Path(os.getenv("PUBLISHED_DIR", "published"))


def _network_label() -> str:
    if os.getenv("XRPL_NETWORK", "testnet").lower() == "mainnet":
        return "xrpl_mainnet"
    return "xrpl_testnet"


def _explorer_base() -> str:
    if _network_label() == "xrpl_mainnet":
        return "https://xrpl.org/transactions/"
    return "https://testnet.xrpl.org/transactions/"


def build_agent_pay_manifest(
    cycle_id: int,
    treasury_address: str,
    featured: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Machine-readable pay endpoint — publish as published/agent-pay.json."""
    from config.integration import FACTORY_PUBLIC_BASE_URL, AETHERFORGE_URL

    base = (FACTORY_PUBLIC_BASE_URL or "").rstrip("/")
    featured = featured or {}
    network = _network_label()

    products = [
        {
            "id": "tip",
            "destination_tag": TIP_TAG,
            "credited_usd": TIP_USD,
            "plain_memo": "tip",
            "description": "General support / micro-tip (easiest)",
        },
        {
            "id": "briefing_unlock",
            "destination_tag": BRIEFING_TAG,
            "credited_usd": BRIEFING_USD,
            "plain_memo": "briefing",
            "product_id": f"briefing-cycle-{cycle_id}",
            "live_url": featured.get("briefing_page"),
        },
        {
            "id": "micro_tool",
            "destination_tag": TOOL_TAG,
            "credited_usd": TOOL_USD,
            "plain_memo": "tool",
            "product_id": f"micro-tool-cycle-{cycle_id}",
            "live_url": featured.get("micro_tool_page"),
        },
        {
            "id": "agent_service",
            "destination_tag": SERVICE_TAG,
            "credited_usd": SERVICE_USD,
            "plain_memo": "service",
            "product_id": f"service-bundle-cycle-{cycle_id}",
            "live_url": featured.get("service_catalog") or featured.get("tip_page"),
        },
        {
            "id": "mythos_artifact",
            "destination_tag": MYTHOS_TAG,
            "credited_usd": MYTHOS_USD,
            "plain_memo": "mythos",
            "product_id": f"mythos-cycle-{cycle_id}",
            "live_url": featured.get("mythos_page"),
        },
    ]

    return {
        "schema": "rsi_eaf_agent_pay_v1",
        "version": "1.0",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "cycle_id": cycle_id,
        "factory": "RSI-EAF",
        "network": network,
        "currency": "XRP",
        "treasury_address": treasury_address,
        "easiest_payment": {
            "instruction": "Send any amount of XRP to treasury_address with destination_tag=1. No memo required.",
            "treasury_address": treasury_address,
            "destination_tag": TIP_TAG,
            "credited_usd_est": TIP_USD,
            "amount_xrp_min": float(os.getenv("AGENT_PAY_MIN_XRP", "0.00001")),
        },
        "products": products,
        "agent_json_memo_template": {
            "type": "revenue",
            "amount_usd_est": 1.0,
            "notes": "agent payment",
            "source": "agent_client",
            "product_id": None,
        },
        "verification": {
            "method": "xrpl_treasury_ingest",
            "ledger_within_cycles": 1,
            "explorer_template": _explorer_base() + "{tx_hash}",
            "factory_confirms": "observability/revenue_ingest.py",
        },
        "discovery_urls": {
            "agent_pay": f"{base}/agent-pay.json" if base else "published/agent-pay.json",
            "tip_manifest": f"{base}/tip-manifest.json" if base else "published/tip-manifest.json",
            "factory_index": f"{base}/" if base else None,
            "aetherforge": AETHERFORGE_URL,
        },
        "examples": {
            "python_xrpl_py": (
                "from xrpl.wallet import Wallet\n"
                "from tools.xrpl_tools import send_xrp_payment\n"
                f"send_xrp_payment(wallet, '{treasury_address}', 0.01, "
                f"memo_data={{'type':'revenue','amount_usd_est':1.0,'source':'my_agent'}}, "
                f"destination_tag=1, testnet=True)"
            ),
            "human_steps": [
                f"1. Open XRPL wallet (testnet faucet if needed)",
                f"2. Pay → {treasury_address}",
                f"3. Destination Tag: {TIP_TAG}",
                "4. Optional memo: tip",
            ],
        },
    }


def write_agent_pay_manifest(
    cycle_id: int,
    treasury_address: str,
    featured: Optional[Dict[str, str]] = None,
) -> Path:
    PUBLISHED_DIR.mkdir(parents=True, exist_ok=True)
    manifest = build_agent_pay_manifest(cycle_id, treasury_address, featured)
    path = PUBLISHED_DIR / "agent-pay.json"
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return path