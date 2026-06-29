"""
Verified revenue ingestion for RSI-EAF.

External XRPL payments to treasury — verified via destination tag, plain memo,
JSON memo, or flat-tip policy (see payment_intent.py).
"""

import os
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set

if TYPE_CHECKING:
    from factory_core.state import FactoryState

from observability.economic_ledger import ledger
from observability.revenue_classification import enrich_revenue_metadata
from observability.payment_intent import (
    decode_memo_entries,
    resolve_payment_intent,
    simple_payment_instructions,
)
from xrpl.utils import drops_to_xrp

from tools.xrpl_tools import (
    FACTORY_XRPL_ADDRESS,
    query_recent_transactions,
)

FACTORY_TREASURY_ADDRESS = os.getenv("FACTORY_TREASURY_ADDRESS")
INTERNAL_ACCOUNTS = {
    addr for addr in (FACTORY_XRPL_ADDRESS, FACTORY_TREASURY_ADDRESS) if addr
}
INGEST_LIMIT = int(os.getenv("REVENUE_INGEST_TX_LIMIT", "200"))


def _extract_payment_fields(tx_entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    tx = tx_entry.get("tx") or tx_entry.get("tx_json") or {}
    if tx.get("TransactionType") != "Payment":
        return None
    if tx_entry.get("validated") is False:
        return None

    json_memos, plain_memos = decode_memo_entries(tx)

    amount_drops = tx.get("Amount") or tx.get("DeliverMax")
    if not amount_drops and tx_entry.get("meta"):
        amount_drops = tx_entry["meta"].get("delivered_amount")

    return {
        "tx_hash": tx.get("hash") or tx_entry.get("hash"),
        "from": tx.get("Account"),
        "destination": tx.get("Destination"),
        "amount_drops": amount_drops,
        "destination_tag": tx.get("DestinationTag"),
        "memos": json_memos,
        "plain_memos": plain_memos,
    }


def _known_tx_hashes() -> Set[str]:
    return {
        e["xrpl_tx_hash"]
        for e in ledger.get_recent_events(limit=1000)
        if e.get("xrpl_tx_hash")
    }


def _is_internal_transfer(sender: Optional[str]) -> bool:
    return bool(sender and sender in INTERNAL_ACCOUNTS)


def _xrp_amount(payment: Dict[str, Any]) -> Optional[float]:
    drops = payment.get("amount_drops")
    if drops and str(drops).isdigit():
        return float(drops_to_xrp(str(drops)))
    return None


def reconcile_unmatched_treasury_payments(cycle_id: int) -> List[Dict[str, Any]]:
    """Re-evaluate prior treasury_inflow_unmatched rows with current payment rules."""
    upgraded: List[Dict[str, Any]] = []
    events = ledger.get_recent_events(limit=1000)
    known = _known_tx_hashes()

    for event in events:
        if event.get("event_type") != "treasury_inflow_unmatched":
            continue
        tx_hash = event.get("xrpl_tx_hash")
        if not tx_hash:
            continue
        if any(
            e.get("event_type") == "revenue" and e.get("xrpl_tx_hash") == tx_hash
            for e in events
        ):
            continue

        from xrpl.models.requests import Tx
        from tools.xrpl_tools import get_client

        try:
            response = get_client(True).request(Tx(transaction=tx_hash))
            entry = {"validated": True, "tx_json": response.result.get("tx_json", {})}
            if response.result.get("meta"):
                entry["meta"] = response.result["meta"]
            entry["tx_json"]["hash"] = tx_hash
            payment = _extract_payment_fields(entry)
        except Exception:
            continue

        if not payment:
            continue

        intent = resolve_payment_intent(payment, cycle_id=cycle_id)
        if not intent:
            continue

        xrp_amount = _xrp_amount(payment)
        revenue = ledger.log_verified_revenue(
            source="xrpl_inbound_payment",
            amount_usd_est=intent.amount_usd_est,
            cycle_id=cycle_id,
            xrpl_tx_hash=tx_hash,
            verification_method=f"xrpl_treasury_{intent.method}",
            metadata=enrich_revenue_metadata(
                {
                    "from_address": payment["from"],
                    "treasury_address": event.get("metadata", {}).get("treasury_address"),
                    "xrp_received": xrp_amount,
                    "notes": intent.notes,
                    "product_id": intent.product_id,
                    "payment_method": intent.method,
                    "destination_tag": intent.destination_tag,
                    "reconciled_from": "treasury_inflow_unmatched",
                },
                payment["from"],
            ),
        )
        meta = event.get("metadata") or {}
        meta["superseded"] = True
        meta["supersede_reason"] = "reconciled_as_verified_revenue"
        meta["revenue_tx_logged"] = tx_hash
        known.add(tx_hash)
        upgraded.append(revenue)
        print(
            f"[RevenueIngest] Reconciled {tx_hash} → ${intent.amount_usd_est:.2f} "
            f"via {intent.method}"
        )

    return upgraded


def ingest_verified_xrpl_revenue(
    cycle_id: int,
    treasury_address: Optional[str] = None,
    factory_state: Optional["FactoryState"] = None,
) -> Dict[str, Any]:
    """
    Scan treasury for external incoming payments; log verified revenue.
    """
    address = treasury_address or FACTORY_TREASURY_ADDRESS
    if not address:
        print("[RevenueIngest] No FACTORY_TREASURY_ADDRESS configured; skipping.")
        return {"ingested": [], "unmatched": [], "reconciled": []}

    known_hashes = _known_tx_hashes()
    ingested: List[Dict[str, Any]] = []
    unmatched: List[Dict[str, Any]] = []

    reconciled = reconcile_unmatched_treasury_payments(cycle_id=cycle_id)
    ingested.extend(reconciled)
    known_hashes.update(e.get("xrpl_tx_hash") for e in reconciled if e.get("xrpl_tx_hash"))

    transactions = query_recent_transactions(address, limit=INGEST_LIMIT)
    instructions = simple_payment_instructions(cycle_id, address)
    for entry in transactions:
        payment = _extract_payment_fields(entry)
        if not payment:
            continue
        if payment["destination"] != address:
            continue
        if _is_internal_transfer(payment["from"]):
            continue

        tx_hash = payment["tx_hash"]
        if not tx_hash or tx_hash in known_hashes:
            continue

        intent = resolve_payment_intent(payment, cycle_id=cycle_id)
        xrp_amount = _xrp_amount(payment)

        if not intent:
            print(
                f"[RevenueIngest] Unmatched {tx_hash}: external payment "
                f"({xrp_amount} XRP) — use Destination Tag {instructions['easiest']['destination_tag']}."
            )
            observed = ledger.log_event(
                event_type="treasury_inflow_unmatched",
                source="xrpl_inbound_payment",
                amount_usd_est=0.0,
                cycle_id=cycle_id,
                xrpl_tx_hash=tx_hash,
                metadata={
                    "from_address": payment["from"],
                    "treasury_address": address,
                    "xrp_received": xrp_amount,
                    "destination_tag": payment.get("destination_tag"),
                    "plain_memos": payment.get("plain_memos"),
                    "memos": payment.get("memos"),
                    "skip_reason": "unrecognized_payment_intent",
                    "simple_instructions": instructions,
                },
                anchor_to_xrpl=False,
            )
            known_hashes.add(tx_hash)
            unmatched.append(observed)
            continue

        event = ledger.log_verified_revenue(
            source="xrpl_inbound_payment",
            amount_usd_est=intent.amount_usd_est,
            cycle_id=cycle_id,
            xrpl_tx_hash=tx_hash,
            verification_method=f"xrpl_treasury_{intent.method}",
            metadata=enrich_revenue_metadata(
                {
                    "from_address": payment["from"],
                    "treasury_address": address,
                    "xrp_received": xrp_amount,
                    "notes": intent.notes,
                    "product_id": intent.product_id,
                    "payment_method": intent.method,
                    "destination_tag": intent.destination_tag,
                    "memos": payment.get("memos"),
                    "plain_memos": payment.get("plain_memos"),
                },
                payment["from"],
            ),
        )
        known_hashes.add(tx_hash)
        ingested.append(event)
        print(
            f"[RevenueIngest] Verified ${intent.amount_usd_est:.2f} from {payment['from']} "
            f"({intent.method})"
        )

    return {"ingested": ingested, "unmatched": unmatched, "reconciled": reconciled}