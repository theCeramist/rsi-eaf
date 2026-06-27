"""
Treasury payment monitor — short WebSocket poll each cycle for inbound revenue.
"""

import os
from typing import Any, Callable, Dict, List, Optional

from observability.revenue_ingest import ingest_verified_xrpl_revenue
from tools.xrpl_tools import FACTORY_XRPL_ADDRESS, monitor_incoming_payments

FACTORY_TREASURY_ADDRESS = os.getenv("FACTORY_TREASURY_ADDRESS")
MONITOR_TIMEOUT = int(os.getenv("TREASURY_MONITOR_TIMEOUT_SEC", "3"))


def poll_treasury_payments(
    cycle_id: int,
    on_payment: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> List[Dict[str, Any]]:
    """
    Listen briefly for treasury payments, then ingest verified revenue into ledger.
    """
    address = FACTORY_TREASURY_ADDRESS or FACTORY_XRPL_ADDRESS
    if not address:
        print("[TreasuryMonitor] No treasury address configured.")
        return []

    captured: List[Dict[str, Any]] = []

    def _callback(tx: Dict[str, Any]) -> None:
        captured.append(tx)
        if on_payment:
            on_payment(tx)
        print(f"[TreasuryMonitor] Inbound payment detected: {tx.get('tx_hash')}")

    try:
        monitor_incoming_payments(
            address=address,
            callback=_callback,
            testnet=True,
            timeout_seconds=MONITOR_TIMEOUT,
        )
    except Exception as exc:
        print(f"[TreasuryMonitor] Monitor ended: {exc}")

    return ingest_verified_xrpl_revenue(cycle_id=cycle_id, treasury_address=address)