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
    factory_state: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Listen briefly for treasury payments, then ingest verified revenue into ledger.
    Returns structured result for cycle instrumentation.
    """
    address = FACTORY_TREASURY_ADDRESS or FACTORY_XRPL_ADDRESS
    if not address:
        print("[TreasuryMonitor] No treasury address configured.")
        return {"ws_observed": 0, "ingested": [], "treasury_address": None}

    captured: List[Dict[str, Any]] = []

    def _callback(tx: Dict[str, Any]) -> None:
        captured.append(tx)
        if on_payment:
            on_payment(tx)
        print(f"[TreasuryMonitor] Inbound payment detected: {tx.get('tx_hash')}")

    ws_observed = monitor_incoming_payments(
        address=address,
        callback=_callback,
        testnet=True,
        timeout_seconds=MONITOR_TIMEOUT,
    )

    ingested = ingest_verified_xrpl_revenue(
        cycle_id=cycle_id,
        treasury_address=address,
        factory_state=factory_state,
    )

    if factory_state is not None and ingested:
        factory_state.set_treasury_watermark(
            last_ingested_tx_hash=ingested[-1].get("xrpl_tx_hash"),
            last_poll_at=cycle_id,
        )

    return {
        "ws_observed": ws_observed,
        "ws_captured": captured,
        "ingested": ingested,
        "treasury_address": address,
    }