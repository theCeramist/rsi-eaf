"""
Real XRPL ledger queries for market intelligence and paid briefings.
"""

import os
from typing import Any, Dict, List, Optional

from tools.xrpl_tools import (
    FACTORY_XRPL_ADDRESS,
    get_account_xrp_balance,
    query_recent_transactions,
)

FACTORY_TREASURY_ADDRESS = os.getenv("FACTORY_TREASURY_ADDRESS", "")


def _count_inbound_payments(transactions: List[Dict[str, Any]], address: str) -> int:
    count = 0
    for entry in transactions:
        tx = entry.get("tx") or entry.get("tx_json") or {}
        if tx.get("TransactionType") != "Payment":
            continue
        if tx.get("Destination") == address and tx.get("Account") != address:
            count += 1
    return count


def gather_factory_intel(cycle_id: int) -> Dict[str, Any]:
    """Collect verifiable on-chain metrics for briefing content."""
    factory_addr = FACTORY_XRPL_ADDRESS
    treasury_addr = FACTORY_TREASURY_ADDRESS

    intel: Dict[str, Any] = {
        "cycle_id": cycle_id,
        "factory_address": factory_addr,
        "treasury_address": treasury_addr,
    }

    if factory_addr:
        try:
            intel["factory_balance_xrp"] = float(get_account_xrp_balance(factory_addr))
            factory_txs = query_recent_transactions(factory_addr, limit=15)
            intel["factory_recent_tx_count"] = len(factory_txs)
        except Exception as exc:
            intel["factory_error"] = str(exc)

    if treasury_addr:
        try:
            intel["treasury_balance_xrp"] = float(get_account_xrp_balance(treasury_addr))
            treasury_txs = query_recent_transactions(treasury_addr, limit=15)
            intel["treasury_recent_tx_count"] = len(treasury_txs)
            intel["treasury_inbound_payments"] = _count_inbound_payments(
                treasury_txs, treasury_addr
            )
        except Exception as exc:
            intel["treasury_error"] = str(exc)

    return intel


def format_briefing_teaser(intel: Dict[str, Any]) -> str:
    lines = [
        f"Cycle {intel.get('cycle_id')} XRPL factory snapshot (live testnet data):",
    ]
    if "factory_balance_xrp" in intel:
        lines.append(f"- Factory wallet balance: {intel['factory_balance_xrp']:.5f} XRP")
    if "treasury_balance_xrp" in intel:
        lines.append(f"- Treasury balance: {intel['treasury_balance_xrp']:.5f} XRP")
    if "treasury_inbound_payments" in intel:
        lines.append(
            f"- Recent inbound treasury payments (sample): {intel['treasury_inbound_payments']}"
        )
    lines.append(
        "- Full briefing includes transaction patterns, revenue memo analysis, "
        "and agent-payment readiness checklist."
    )
    return "\n".join(lines)


def format_briefing_full(intel: Dict[str, Any]) -> str:
    teaser = format_briefing_teaser(intel)
    extra = [
        "",
        "## Full Intelligence Report",
        f"Factory address: `{intel.get('factory_address') or 'n/a'}`",
        f"Treasury address: `{intel.get('treasury_address') or 'n/a'}`",
    ]
    if intel.get("factory_recent_tx_count") is not None:
        extra.append(f"Factory sampled transactions: {intel['factory_recent_tx_count']}")
    if intel.get("treasury_recent_tx_count") is not None:
        extra.append(f"Treasury sampled transactions: {intel['treasury_recent_tx_count']}")
    extra.extend([
        "",
        "### Agent Payment Readiness",
        "1. Publish machine-readable tip manifest at `/tip-manifest.json`.",
        "2. Accept treasury payments with `type: revenue` memos.",
        "3. Ingest verified inflows via WebSocket + AccountTx polling.",
        "4. Gate evolution on live URL + XRPL confirmation.",
        "",
        "### Monetization Priority",
        "Highest impact: tipping funnel + gated briefings with explicit product_id memos.",
    ])
    return teaser + "\n" + "\n".join(extra)