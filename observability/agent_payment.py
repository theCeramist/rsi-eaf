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
    try:
        from factory_core.xrpl_network import network_label, revenue_network

        return network_label(revenue_network())
    except Exception:
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
    # Prefer public revenue treasury (mainnet when ready)
    try:
        from factory_core.xrpl_network import (
            explorer_account_url,
            mainnet_treasury_address,
            network_label,
            resolve_public_treasury,
            testnet_treasury_address,
        )

        pub_addr, pub_net = resolve_public_treasury()
        if pub_addr:
            treasury_address = pub_addr
        network = network_label(pub_net)
        is_mainnet = pub_net == "mainnet"
        dual = {
            "mainnet": mainnet_treasury_address() or None,
            "testnet": testnet_treasury_address() or None,
            "primary_network": pub_net,
            "primary_explorer": explorer_account_url(treasury_address, pub_net),
        }
    except Exception:
        network = _network_label()
        is_mainnet = network == "xrpl_mainnet"
        dual = {}

    deliverable_base = f"{base}/deliverables" if base else "published/deliverables"
    products = [
        {
            "id": "tip",
            "destination_tag": TIP_TAG,
            "credited_usd": TIP_USD,
            "plain_memo": "tip",
            "description": "General support / micro-tip (easiest)",
            "service_type": "donation",
        },
        {
            "id": "briefing_unlock",
            "destination_tag": BRIEFING_TAG,
            "credited_usd": BRIEFING_USD,
            "plain_memo": "briefing",
            "product_id": f"briefing-cycle-{cycle_id}",
            "live_url": featured.get("briefing_page"),
            "description": "XRPL factory intelligence briefing (HTML preview + JSON deliverable after pay)",
            "fulfillment_url": f"{deliverable_base}/briefing-cycle-{cycle_id}.json",
            "service_type": "paid_report",
        },
        {
            "id": "micro_tool",
            "destination_tag": TOOL_TAG,
            "credited_usd": TOOL_USD,
            "plain_memo": "tool",
            "product_id": f"micro-tool-cycle-{cycle_id}",
            "live_url": featured.get("micro_tool_page"),
            "description": "Treasury payment validator spec for wallet/agent integrators",
            "fulfillment_url": f"{deliverable_base}/micro-tool-cycle-{cycle_id}.json",
            "service_type": "paid_tool",
        },
        {
            "id": "agent_service",
            "destination_tag": SERVICE_TAG,
            "credited_usd": SERVICE_USD,
            "plain_memo": "service",
            "product_id": f"service-bundle-cycle-{cycle_id}",
            "live_url": featured.get("service_catalog") or featured.get("tip_page"),
            "description": "Cycle intel bundle: ledger net, trace phases, orchestrator metadata",
            "fulfillment_url": f"{deliverable_base}/service-bundle-cycle-{cycle_id}.json",
            "service_type": "agent_api",
        },
        {
            "id": "mythos_artifact",
            "destination_tag": MYTHOS_TAG,
            "credited_usd": MYTHOS_USD,
            "plain_memo": "mythos",
            "product_id": f"mythos-cycle-{cycle_id}",
            "live_url": featured.get("mythos_page"),
            "description": "Narrative commerce artifact for aetherforge lane",
            "fulfillment_url": f"{deliverable_base}/mythos-cycle-{cycle_id}.json",
            "service_type": "creative_commerce",
        },
    ]

    min_xrp = float(os.getenv("AGENT_PAY_MIN_XRP", "0.00001" if not is_mainnet else "0.01"))
    xrp_usd = float(os.getenv("XRP_USD_EST", "1.07"))
    try:
        import httpx

        pr = httpx.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": "ripple", "vs_currencies": "usd"},
            timeout=6,
        )
        if pr.status_code == 200:
            xrp_usd = float((pr.json().get("ripple") or {}).get("usd") or xrp_usd)
    except Exception:
        pass

    def _xrp(usd: float) -> float:
        if xrp_usd <= 0:
            return float(usd)
        return round(max(usd / xrp_usd, min_xrp) * 1.02, 6)

    # Unfunded mainnet accounts need ≥1 XRP base reserve on first inbound
    activated = True
    if is_mainnet:
        try:
            ready_p = Path(os.getenv("OBSERVABILITY_DIR", "observability")) / "mainnet_readiness.json"
            if ready_p.exists():
                ready = json.loads(ready_p.read_text(encoding="utf-8"))
                activated = bool(
                    (ready.get("ready_accept_unfunded") or {})
                    .get("checks", {})
                    .get("account_activated", True)
                )
        except Exception:
            activated = False
    tip_xrp = max(_xrp(TIP_USD), 1.0 if (is_mainnet and not activated) else _xrp(TIP_USD))

    # Enrich products with mainnet XRP amounts + wallet deep links
    try:
        from tools.mainnet_pay_surface import xaman_pay_url, xrpl_uri
    except Exception:
        xaman_pay_url = xrpl_uri = None  # type: ignore

    for p in products:
        usd = float(p.get("credited_usd") or 1)
        ax = max(_xrp(usd), tip_xrp if p.get("destination_tag") == TIP_TAG else _xrp(usd))
        if is_mainnet and not activated:
            ax = max(ax, 1.0)
        p["amount_xrp_recommended"] = ax
        p["amount_drops_recommended"] = str(int(ax * 1_000_000))
        p["xrp_usd_est"] = xrp_usd
        if xaman_pay_url and treasury_address:
            p["xaman_pay_url"] = xaman_pay_url(
                treasury_address, amount_xrp=ax, dt=int(p["destination_tag"])
            )
            p["payment_uri"] = xrpl_uri(
                treasury_address, amount_xrp=ax, dt=int(p["destination_tag"])
            )
        if is_mainnet:
            p["network"] = "xrpl_mainnet"
            p["real_value"] = True

    return {
        "schema": "rsi_eaf_agent_pay_v1",
        "version": "1.2",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "cycle_id": cycle_id,
        "factory": "RSI-EAF",
        "network": network,
        "currency": "XRP",
        "real_value": bool(is_mainnet),
        "value_proposition": {
            "for_humans": (
                "Fund a recursive self-improving economic agent factory; "
                "Tag 2+ unlocks exclusive ICP deliverables on mainnet."
            ),
            "for_agents": (
                "Machine-payable SKUs via destination tags; fulfillment JSON at "
                "discovery_urls after on-ledger confirmation. Prefer mainnet."
            ),
            "proof": "Economic ledger only credits verified XRPL mainnet payments — no spoofed revenue.",
            "exclusive_icp": True,
        },
        "treasury_address": treasury_address,
        "treasury_map": dual or None,
        "account_activated": activated if is_mainnet else None,
        "base_reserve_xrp": 1.0 if is_mainnet else None,
        "xrp_usd_est": xrp_usd,
        "easiest_payment": {
            "instruction": (
                f"Send XRP on {network} to treasury_address with destination_tag=1. No memo required."
                + (
                    " MAINNET — real XRP with real USD value."
                    if is_mainnet
                    else " Testnet XRP only (no market value)."
                )
                + (
                    f" First payment should be ≥ {tip_xrp} XRP to activate unfunded account (base reserve 1 XRP)."
                    if is_mainnet and not activated
                    else ""
                )
            ),
            "treasury_address": treasury_address,
            "destination_tag": TIP_TAG,
            "credited_usd_est": TIP_USD,
            "amount_xrp_min": min_xrp,
            "amount_xrp_recommended": tip_xrp,
            "amount_drops_recommended": str(int(tip_xrp * 1_000_000)),
            "network": network,
            "real_value": bool(is_mainnet),
            "xaman_pay_url": (
                xaman_pay_url(treasury_address, amount_xrp=tip_xrp, dt=TIP_TAG)
                if xaman_pay_url and treasury_address
                else None
            ),
            "payment_uri": (
                xrpl_uri(treasury_address, amount_xrp=tip_xrp, dt=TIP_TAG)
                if xrpl_uri and treasury_address
                else None
            ),
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
            "payment_status": f"{base}/payment-status.json" if base else "published/payment-status.json",
            "fulfillment_index": f"{base}/deliverables/fulfillment-index.json" if base else "published/deliverables/fulfillment-index.json",
            "factory_index": f"{base}/" if base else None,
            "aetherforge": AETHERFORGE_URL,
        },
        "examples": {
            "python_xrpl_py": (
                "from tools.xrpl_tools import send_xrp_payment\n"
                f"send_xrp_payment(wallet, '{treasury_address}', 0.01, "
                f"memo_data={{'type':'revenue','amount_usd_est':1.0,'source':'my_agent'}}, "
                f"destination_tag=1, testnet={str(not is_mainnet)})"
            ),
            "human_steps": [
                f"1. Open XRPL wallet on {network}"
                + (" (real XRP)" if is_mainnet else " (testnet faucet OK)"),
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
    if os.getenv("X402_PUBLISH_ENABLED", "true").lower() in {"1", "true", "yes"}:
        try:
            from observability.x402_publish import write_x402_surfaces

            paths = write_x402_surfaces(manifest)
            return paths["agent_pay"]
        except Exception:
            pass
    path = PUBLISHED_DIR / "agent-pay.json"
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return path