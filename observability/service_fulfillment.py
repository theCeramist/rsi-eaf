"""
Paid service fulfillment — deliver real artifacts when treasury payments arrive.

Agents and humans pay via agent-pay.json / service-catalog.json; this module
materializes JSON deliverables they can fetch after payment.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from observability.economic_ledger import ledger
from observability.payment_intent import (
    BRIEFING_TAG,
    BRIEFING_USD,
    MYTHOS_TAG,
    MYTHOS_USD,
    SERVICE_TAG,
    SERVICE_USD,
    TOOL_TAG,
    TOOL_USD,
    resolve_payment_intent,
)
from observability.revenue_ingest import _extract_payment_fields
from tools.xrpl_research import gather_factory_intel, format_briefing_full
from tools.xrpl_tools import FACTORY_XRPL_ADDRESS, query_recent_transactions

PUBLISHED_DIR = Path(os.getenv("PUBLISHED_DIR", "published"))
DELIVERABLES_DIR = PUBLISHED_DIR / "deliverables"
FULFILLMENT_INDEX = DELIVERABLES_DIR / "fulfillment-index.json"
INGEST_LIMIT = int(os.getenv("REVENUE_INGEST_TX_LIMIT", "40"))
FACTORY_PUBLIC_BASE_URL = os.getenv("FACTORY_PUBLIC_BASE_URL", "").rstrip("/")


def sellable_services(cycle_id: int, treasury: str, featured: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    """Canonical paid offerings — each maps payment → concrete deliverable."""
    base = FACTORY_PUBLIC_BASE_URL or "https://published-zeta.vercel.app"
    featured = featured or {}
    return [
        {
            "id": "xrpl_market_briefing",
            "product_id": f"briefing-cycle-{cycle_id}",
            "title": "XRPL Factory Intelligence Briefing",
            "description": "Live testnet treasury/factory metrics, inbound payment patterns, agent-pay readiness.",
            "price_usd": BRIEFING_USD,
            "payment": {"destination_tag": BRIEFING_TAG, "plain_memo": "briefing"},
            "deliverable_type": "html+json",
            "preview_url": featured.get("briefing_page") or f"{base}/briefing-cycle-{cycle_id}.html",
            "fulfillment_url": f"{base}/deliverables/briefing-cycle-{cycle_id}.json",
            "buyer": "humans and research agents",
        },
        {
            "id": "treasury_tip_validator",
            "product_id": f"micro-tool-cycle-{cycle_id}",
            "title": "XRPL Treasury Payment Validator",
            "description": "Machine-readable rules + worked examples to verify tip/briefing payments hit RSI-EAF treasury.",
            "price_usd": TOOL_USD,
            "payment": {"destination_tag": TOOL_TAG, "plain_memo": "tool"},
            "deliverable_type": "json",
            "preview_url": featured.get("micro_tool_page") or f"{base}/micro-tool-cycle-{cycle_id}.html",
            "fulfillment_url": f"{base}/deliverables/micro-tool-cycle-{cycle_id}.json",
            "buyer": "wallet integrators and paying agents",
        },
        {
            "id": "agent_cycle_intel_bundle",
            "product_id": f"service-bundle-cycle-{cycle_id}",
            "title": "Factory Cycle Intelligence Bundle",
            "description": "Cycle trace summary, ledger economics, nexus sync metadata — for orchestrator agents.",
            "price_usd": SERVICE_USD,
            "payment": {"destination_tag": SERVICE_TAG, "plain_memo": "service"},
            "deliverable_type": "json",
            "preview_url": featured.get("service_catalog") or f"{base}/service-catalog.json",
            "fulfillment_url": f"{base}/deliverables/service-bundle-cycle-{cycle_id}.json",
            "buyer": "ACP / swarm orchestrator agents",
        },
        {
            "id": "mythos_narrative_artifact",
            "product_id": f"mythos-cycle-{cycle_id}",
            "title": "Mythos Commerce Narrative Artifact",
            "description": "Cycle-scoped story artifact tied to aetherforge commerce lane.",
            "price_usd": MYTHOS_USD,
            "payment": {"destination_tag": MYTHOS_TAG, "plain_memo": "mythos"},
            "deliverable_type": "json",
            "preview_url": featured.get("mythos_page"),
            "fulfillment_url": f"{base}/deliverables/mythos-cycle-{cycle_id}.json",
            "buyer": "creators and narrative commerce agents",
        },
    ]


def build_service_catalog(
    cycle_id: int,
    treasury: str,
    featured: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    services = sellable_services(cycle_id, treasury, featured)
    base = FACTORY_PUBLIC_BASE_URL or "https://published-zeta.vercel.app"
    return {
        "schema": "rsi_eaf_service_catalog_v2",
        "cycle_id": cycle_id,
        "treasury_address": treasury,
        "network": "xrpl_testnet",
        "factory": "RSI-EAF",
        "how_to_pay": {
            "human": f"Pay treasury with Destination Tag (see each service). Manifest: {base}/agent-pay.json",
            "agent": f"GET {base}/agent-pay.json then send XRP with matching destination_tag + optional JSON memo",
        },
        "services": services,
        "acp_ready": True,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def write_service_catalog(
    cycle_id: int,
    treasury: str,
    featured: Optional[Dict[str, str]] = None,
) -> Path:
    PUBLISHED_DIR.mkdir(parents=True, exist_ok=True)
    catalog = build_service_catalog(cycle_id, treasury, featured)
    path = PUBLISHED_DIR / "service-catalog.json"
    path.write_text(json.dumps(catalog, indent=2), encoding="utf-8")
    return path


def _internal_accounts(treasury: str) -> Set[str]:
    return {a for a in (FACTORY_XRPL_ADDRESS, treasury) if a}


def find_paid_product_ids(treasury: str, cycle_id: int) -> Dict[str, str]:
    """Map product_id → tx_hash for external treasury payments with recognized intent."""
    paid: Dict[str, str] = {}
    for entry in query_recent_transactions(treasury, limit=INGEST_LIMIT):
        payment = _extract_payment_fields(entry)
        if not payment or payment.get("from") in _internal_accounts(treasury):
            continue
        intent = resolve_payment_intent(payment, cycle_id=cycle_id)
        if intent and intent.product_id:
            paid[intent.product_id] = payment.get("tx_hash") or ""
    for event in ledger.get_recent_events(limit=500):
        if event.get("event_type") != "revenue":
            continue
        meta = event.get("metadata") or {}
        if meta.get("superseded"):
            continue
        pid = meta.get("product_id")
        if pid:
            paid[pid] = event.get("xrpl_tx_hash") or paid.get(pid, "")
    return paid


def _load_fulfillment_index() -> Dict[str, Any]:
    if not FULFILLMENT_INDEX.exists():
        return {"fulfilled": {}}
    try:
        return json.loads(FULFILLMENT_INDEX.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"fulfilled": {}}


def _save_fulfillment_index(index: Dict[str, Any]) -> None:
    DELIVERABLES_DIR.mkdir(parents=True, exist_ok=True)
    index["updated_at"] = datetime.now(timezone.utc).isoformat()
    FULFILLMENT_INDEX.write_text(json.dumps(index, indent=2), encoding="utf-8")


def _briefing_deliverable(cycle_id: int, product_id: str, tx_hash: str) -> Dict[str, Any]:
    intel = gather_factory_intel(cycle_id)
    return {
        "schema": "rsi_eaf_deliverable_briefing_v1",
        "product_id": product_id,
        "cycle_id": cycle_id,
        "paid_tx_hash": tx_hash,
        "fulfilled_at": datetime.now(timezone.utc).isoformat(),
        "briefing_text": format_briefing_full(intel),
        "intel": intel,
    }


def _validator_deliverable(cycle_id: int, treasury: str, product_id: str, tx_hash: str) -> Dict[str, Any]:
    return {
        "schema": "rsi_eaf_deliverable_validator_v1",
        "product_id": product_id,
        "cycle_id": cycle_id,
        "paid_tx_hash": tx_hash,
        "fulfilled_at": datetime.now(timezone.utc).isoformat(),
        "treasury_address": treasury,
        "validation_rules": {
            "tip": {"destination_tag": 1, "credited_usd": 1.0, "plain_memos": ["tip", "support"]},
            "briefing": {"destination_tag": 2, "credited_usd": 2.0, "product_id_pattern": "briefing-cycle-*"},
            "tool": {"destination_tag": 3, "credited_usd": 3.0, "product_id_pattern": "micro-tool-cycle-*"},
            "service": {"destination_tag": 4, "credited_usd": 2.5, "product_id_pattern": "service-bundle-cycle-*"},
        },
        "verify_steps": [
            "Query treasury account txs via XRPL JSON-RPC account_tx",
            "Confirm TransactionType=Payment, Destination=treasury_address",
            "Match DestinationTag or memo to validation_rules",
            "Ingest path: observability/revenue_ingest.py",
        ],
        "agent_pay_url": f"{FACTORY_PUBLIC_BASE_URL}/agent-pay.json" if FACTORY_PUBLIC_BASE_URL else None,
    }


def _cycle_intel_deliverable(cycle_id: int, product_id: str, tx_hash: str) -> Dict[str, Any]:
    net = ledger.calculate_net()
    trace_path = Path(os.getenv("FACTORY_TRACE_FILE", "observability/cycle_traces.jsonl"))
    traces: List[Dict[str, Any]] = []
    if trace_path.exists():
        for line in trace_path.read_text(encoding="utf-8").strip().splitlines()[-80:]:
            try:
                row = json.loads(line)
                if row.get("cycle_id") == cycle_id:
                    traces.append({"phase": row.get("phase"), "timestamp": row.get("timestamp")})
            except json.JSONDecodeError:
                continue
    return {
        "schema": "rsi_eaf_deliverable_cycle_intel_v1",
        "product_id": product_id,
        "cycle_id": cycle_id,
        "paid_tx_hash": tx_hash,
        "fulfilled_at": datetime.now(timezone.utc).isoformat(),
        "ledger_net": net,
        "cycle_phases_observed": traces[-12:],
        "nexus_note": "Full nexus wave on jarvis-swarm; request cycle_id for deep trace.",
    }


def _mythos_deliverable(cycle_id: int, product_id: str, tx_hash: str) -> Dict[str, Any]:
    return {
        "schema": "rsi_eaf_deliverable_mythos_v1",
        "product_id": product_id,
        "cycle_id": cycle_id,
        "paid_tx_hash": tx_hash,
        "fulfilled_at": datetime.now(timezone.utc).isoformat(),
        "artifact": {
            "title": f"Mythos Thread — Cycle {cycle_id}",
            "narrative": (
                f"Factory cycle {cycle_id} commerce lane: treasury-grounded mythos artifact. "
                "Payment unlocks this JSON; surface also on aetherforge.world CTA."
            ),
            "aetherforge_url": os.getenv("AETHERFORGE_URL", "https://aetherforge.world"),
        },
    }


def _build_deliverable(
    product_id: str,
    cycle_id: int,
    treasury: str,
    tx_hash: str,
) -> Optional[Dict[str, Any]]:
    if product_id.startswith("briefing-cycle-"):
        return _briefing_deliverable(cycle_id, product_id, tx_hash)
    if product_id.startswith("micro-tool-cycle-"):
        return _validator_deliverable(cycle_id, treasury, product_id, tx_hash)
    if product_id.startswith("service-bundle-cycle-"):
        return _cycle_intel_deliverable(cycle_id, product_id, tx_hash)
    if product_id.startswith("mythos-cycle-"):
        return _mythos_deliverable(cycle_id, product_id, tx_hash)
    return None


def fulfill_paid_services(
    cycle_id: int,
    treasury_address: str,
    *,
    featured: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    Generate deliverable JSON files for every paid product_id not yet fulfilled.
    """
    DELIVERABLES_DIR.mkdir(parents=True, exist_ok=True)
    index = _load_fulfillment_index()
    fulfilled_before = set(index.get("fulfilled", {}).keys())
    paid = find_paid_product_ids(treasury_address, cycle_id)
    newly_fulfilled: List[Dict[str, Any]] = []
    pending: List[str] = []

    for product_id, tx_hash in paid.items():
        if product_id in fulfilled_before:
            continue
        payload = _build_deliverable(product_id, cycle_id, treasury_address, tx_hash)
        if not payload:
            pending.append(product_id)
            continue
        out_path = DELIVERABLES_DIR / f"{product_id}.json"
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        index.setdefault("fulfilled", {})[product_id] = {
            "path": str(out_path),
            "tx_hash": tx_hash,
            "cycle_id": cycle_id,
            "fulfilled_at": payload.get("fulfilled_at"),
        }
        newly_fulfilled.append({"product_id": product_id, "path": str(out_path), "tx_hash": tx_hash})
        print(f"[ServiceFulfillment] Delivered {product_id} → {out_path}")

    if newly_fulfilled:
        _save_fulfillment_index(index)

    catalog_path = write_service_catalog(cycle_id, treasury_address, featured)

    return {
        "paid_product_ids": list(paid.keys()),
        "newly_fulfilled": newly_fulfilled,
        "pending_unknown": pending,
        "catalog_path": str(catalog_path),
        "fulfillment_index": str(FULFILLMENT_INDEX),
    }