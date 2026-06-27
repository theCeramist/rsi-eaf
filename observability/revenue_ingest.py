"""
Verified revenue ingestion for RSI-EAF.

Only logs revenue when there is a queryable inflow — external XRPL payments
to the factory treasury. Internal operational transfers are excluded.
"""

import json
import os
from typing import Any, Dict, List, Optional, Set

from observability.economic_ledger import ledger
from xrpl.utils import drops_to_xrp

from tools.xrpl_tools import (
    FACTORY_XRPL_ADDRESS,
    query_recent_transactions,
)

FACTORY_TREASURY_ADDRESS = os.getenv("FACTORY_TREASURY_ADDRESS")
INTERNAL_ACCOUNTS = {
    addr for addr in (FACTORY_XRPL_ADDRESS, FACTORY_TREASURY_ADDRESS) if addr
}
INGEST_LIMIT = int(os.getenv("REVENUE_INGEST_TX_LIMIT", "20"))


def _decode_memo_data(hex_data: str) -> Optional[Dict[str, Any]]:
    try:
        raw = bytes.fromhex(hex_data)
        return json.loads(raw.decode("utf-8"))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def _extract_payment_fields(tx_entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    tx = tx_entry.get("tx") or tx_entry.get("tx_json") or {}
    if tx.get("TransactionType") != "Payment":
        return None
    if tx_entry.get("validated") is False:
        return None

    memos = []
    for memo_wrap in tx.get("Memos") or []:
        memo = memo_wrap.get("Memo", memo_wrap)
        if memo.get("MemoData"):
            decoded = _decode_memo_data(memo["MemoData"])
            if decoded:
                memos.append(decoded)

    return {
        "tx_hash": tx.get("hash") or tx_entry.get("hash"),
        "from": tx.get("Account"),
        "destination": tx.get("Destination"),
        "amount_drops": tx.get("Amount"),
        "memos": memos,
    }


def _already_logged(tx_hashes: Set[str], tx_hash: str) -> bool:
    return tx_hash in tx_hashes


def _is_internal_transfer(sender: Optional[str]) -> bool:
    return bool(sender and sender in INTERNAL_ACCOUNTS)


def ingest_verified_xrpl_revenue(
    cycle_id: int,
    treasury_address: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Scan treasury for external incoming payments not yet in the ledger.
    Logs each as verified revenue only when inflow is from a non-factory account.
    """
    address = treasury_address or FACTORY_TREASURY_ADDRESS
    if not address:
        print("[RevenueIngest] No FACTORY_TREASURY_ADDRESS configured; skipping.")
        return []

    known_hashes = {
        e["xrpl_tx_hash"]
        for e in ledger.get_recent_events(limit=1000)
        if e.get("xrpl_tx_hash")
    }

    ingested: List[Dict[str, Any]] = []
    transactions = query_recent_transactions(address, limit=INGEST_LIMIT)

    for entry in transactions:
        payment = _extract_payment_fields(entry)
        if not payment:
            continue
        if payment["destination"] != address:
            continue
        if _is_internal_transfer(payment["from"]):
            continue

        tx_hash = payment["tx_hash"]
        if not tx_hash or _already_logged(known_hashes, tx_hash):
            continue

        amount_usd_est = 0.0
        memo_notes = None
        for memo in payment["memos"]:
            if memo.get("type") == "revenue" and memo.get("amount_usd_est"):
                amount_usd_est = float(memo["amount_usd_est"])
                memo_notes = memo.get("notes")
                break

        if amount_usd_est <= 0:
            # No verified USD value in memo — skip rather than invent revenue.
            print(
                f"[RevenueIngest] Skipping {tx_hash}: external payment without "
                "verifiable amount_usd_est in memo."
            )
            continue

        xrp_amount = None
        if payment["amount_drops"] and str(payment["amount_drops"]).isdigit():
            xrp_amount = float(drops_to_xrp(str(payment["amount_drops"])))

        event = ledger.log_verified_revenue(
            source="xrpl_inbound_payment",
            amount_usd_est=amount_usd_est,
            cycle_id=cycle_id,
            xrpl_tx_hash=tx_hash,
            verification_method="xrpl_treasury_inbound",
            metadata={
                "from_address": payment["from"],
                "treasury_address": address,
                "xrp_received": xrp_amount,
                "notes": memo_notes,
                "memos": payment["memos"],
            },
        )
        known_hashes.add(tx_hash)
        ingested.append(event)
        print(f"[RevenueIngest] Verified revenue ${amount_usd_est:.4f} from {payment['from']}")

    return ingested