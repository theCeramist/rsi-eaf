"""
Ledger hygiene — supersede unverified legacy revenue rows.
"""

import json
from typing import Any, Dict, List

from observability.economic_ledger import ledger


def supersede_unverified_revenue() -> List[Dict[str, Any]]:
    """Mark legacy revenue without verified metadata as superseded (amount zeroed)."""
    events = ledger.get_recent_events(limit=1000)
    superseded: List[Dict[str, Any]] = []
    changed = False

    for event in events:
        if event.get("event_type") != "revenue":
            continue
        meta = event.get("metadata") or {}
        if meta.get("verified") is True or meta.get("superseded"):
            continue

        original = float(event.get("amount_usd_est", 0))
        meta["original_amount_usd_est"] = original
        meta["superseded"] = True
        meta["supersede_reason"] = "unverified_legacy_revenue"
        event["metadata"] = meta
        event["amount_usd_est"] = 0.0
        changed = True
        superseded.append({"source": event.get("source"), "original_amount": original})

    if changed:
        with open(ledger.ledger_path, "w", encoding="utf-8") as f:
            for event in events:
                f.write(json.dumps(event, default=str) + "\n")
        print(f"[LedgerHygiene] Superseded {len(superseded)} unverified revenue event(s).")

    return superseded