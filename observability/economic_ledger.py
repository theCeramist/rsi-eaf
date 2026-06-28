"""
Economic Ledger for RSI-EAF
Records all revenue, costs, and value events with strong grounding in XRPL transactions.

Combines local persistent storage (JSONL for simplicity + git) with on-chain anchoring.
Every logged event should ideally correspond to (or reference) a real XRPL Payment tx hash.

This makes economic reality undeniable and queryable via explorers and code.
"""

import json
import os
import time
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from decimal import Decimal

from tools.xrpl_tools import (
    send_xrp_payment,
    get_account_xrp_balance,
    get_revenue_destination,
    load_factory_wallet,
)


LEDGER_FILE = os.getenv("ECONOMIC_LEDGER_FILE", "observability/economic_ledger.jsonl")
FACTORY_XRPL_ADDRESS = os.getenv("FACTORY_XRPL_ADDRESS")  # For anchoring


class EconomicLedger:
    def __init__(self, ledger_path: str = LEDGER_FILE):
        self.ledger_path = ledger_path
        os.makedirs(os.path.dirname(ledger_path) or ".", exist_ok=True)
        self._ensure_file()

    def _ensure_file(self):
        if not os.path.exists(self.ledger_path):
            with open(self.ledger_path, "w") as f:
                f.write("")  # Start empty JSONL

    def log_event(
        self,
        event_type: str,           # "revenue", "cost", "internal_transfer", "milestone"
        source: str,               # e.g. "content_engine_v0.1", "skill_improvement"
        amount_usd_est: float,     # Estimated or actual USD value (for human readability)
        xrpl_tx_hash: Optional[str] = None,
        cycle_id: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
        anchor_to_xrpl: bool = True,
    ) -> Dict[str, Any]:
        """
        Log an economic event. If anchor_to_xrpl and no xrpl_tx_hash provided,
        attempts to send a small anchoring Payment with the event metadata as Memo.
        """
        timestamp = datetime.now(timezone.utc).isoformat()
        event = {
            "timestamp": timestamp,
            "event_type": event_type,
            "source": source,
            "amount_usd_est": amount_usd_est,
            "cycle_id": cycle_id,
            "xrpl_tx_hash": xrpl_tx_hash,
            "metadata": metadata or {},
            "explorer_url": (
                f"https://testnet.xrpl.org/transactions/{xrpl_tx_hash}"
                if xrpl_tx_hash
                else None
            ),
        }

        # Optional: Auto-anchor to XRPL by sending a minimal payment with full metadata
        if anchor_to_xrpl and not xrpl_tx_hash:
            try:
                wallet = load_factory_wallet(testnet=True)
                destination = get_revenue_destination(wallet)
                memo = {
                    "cycle": cycle_id,
                    "source": source,
                    "type": event_type,
                    "amount_usd_est": amount_usd_est,
                    "event_timestamp": timestamp,
                    **(metadata or {}),
                }
                # Send tiny amount (e.g. 0.0001 XRP) as economic anchor
                result = send_xrp_payment(
                    wallet=wallet,
                    destination=destination,
                    amount_xrp=0.0001,
                    memo_data=memo,
                    verbose=False,
                )
                if result.get("success"):
                    event["xrpl_tx_hash"] = result["tx_hash"]
                    event["explorer_url"] = result["explorer_url"]
                    print(f"[EconomicLedger] Anchored event on XRPL: {result['explorer_url']}")
            except Exception as e:
                print(f"[EconomicLedger] XRPL anchoring failed (non-fatal): {e}")

        # Append to local ledger (JSONL - append-only, git friendly)
        with open(self.ledger_path, "a") as f:
            f.write(json.dumps(event, default=str) + "\n")

        return event

    def log_verified_revenue(
        self,
        source: str,
        amount_usd_est: float,
        cycle_id: int,
        xrpl_tx_hash: str,
        verification_method: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Log revenue only when backed by a verifiable inflow (tx hash + verification method).
        Refuses zero/negative amounts or missing proof.
        """
        if amount_usd_est <= 0:
            raise ValueError("Verified revenue requires amount_usd_est > 0")
        if not xrpl_tx_hash:
            raise ValueError("Verified revenue requires xrpl_tx_hash")
        if not verification_method:
            raise ValueError("Verified revenue requires verification_method")

        return self.log_event(
            event_type="revenue",
            source=source,
            amount_usd_est=amount_usd_est,
            cycle_id=cycle_id,
            xrpl_tx_hash=xrpl_tx_hash,
            metadata={
                "verification_method": verification_method,
                "verified": True,
                **(metadata or {}),
            },
            anchor_to_xrpl=False,
        )

    def get_recent_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return the most recent events (newest last)."""
        events = []
        if os.path.exists(self.ledger_path):
            with open(self.ledger_path, "r") as f:
                for line in f:
                    if line.strip():
                        events.append(json.loads(line))
        return events[-limit:]

    def calculate_net(self, since_cycle: Optional[int] = None) -> Dict[str, float]:
        """Simple net calculation for quick health checks."""
        events = self.get_recent_events(limit=1000)
        total_revenue = 0.0
        organic_revenue = 0.0
        factory_adjacent_revenue = 0.0
        total_cost = 0.0
        for e in events:
            if since_cycle and e.get("cycle_id", 0) < since_cycle:
                continue
            meta = e.get("metadata") or {}
            if meta.get("superseded"):
                continue
            amt = float(e.get("amount_usd_est", 0))
            if e["event_type"] == "revenue":
                if meta.get("verified") is not True and amt > 0 and not meta.get("verification_method"):
                    continue
                total_revenue += amt
                if meta.get("revenue_class") == "organic" or meta.get("organic") is True:
                    organic_revenue += amt
                elif meta.get("revenue_class") == "factory_adjacent":
                    factory_adjacent_revenue += amt
            elif e["event_type"] == "cost":
                total_cost += amt
        return {
            "total_revenue_usd_est": round(total_revenue, 4),
            "organic_revenue_usd_est": round(organic_revenue, 4),
            "factory_adjacent_revenue_usd_est": round(factory_adjacent_revenue, 4),
            "total_cost_usd_est": round(total_cost, 4),
            "net_usd_est": round(total_revenue - total_cost, 4),
            "organic_net_usd_est": round(organic_revenue - total_cost, 4),
            "events_counted": len(events),
        }

    def get_xrpl_anchored_events(self) -> List[Dict[str, Any]]:
        """Filter events that have a real XRPL tx hash."""
        return [e for e in self.get_recent_events(1000) if e.get("xrpl_tx_hash")]


# Convenience singleton for easy import across the factory
ledger = EconomicLedger()


# Example usage / quick test
if __name__ == "__main__":
    print("=== Economic Ledger Test (with XRPL anchoring) ===")
    test_event = ledger.log_event(
        event_type="revenue",
        source="bootstrap_test",
        amount_usd_est=0.42,
        cycle_id=0,
        metadata={"note": "First grounded economic event via scaffold", "test": True},
        anchor_to_xrpl=True,
    )
    print("Logged event:", json.dumps(test_event, indent=2, default=str))

    print("\nRecent events:", len(ledger.get_recent_events(5)))
    print("Current net:", ledger.calculate_net())
