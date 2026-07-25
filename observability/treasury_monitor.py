"""
Treasury payment monitor — inbox drain + ingest each cycle (no blocking duplicate WS).
"""

import os
from typing import Any, Callable, Dict, List, Optional

from observability.revenue_ingest import ingest_verified_xrpl_revenue
from tools.xrpl_tools import FACTORY_XRPL_ADDRESS

FACTORY_TREASURY_ADDRESS = os.getenv("FACTORY_TREASURY_ADDRESS")
MONITOR_TIMEOUT = int(os.getenv("TREASURY_MONITOR_TIMEOUT_SEC", "5"))
SKIP_INLINE_WS = os.getenv("TREASURY_SKIP_INLINE_WS_WHEN_DAEMON", "true").lower() in {
    "1",
    "true",
    "yes",
}


def _daemon_active() -> bool:
    try:
        from observability.treasury_daemon import is_treasury_daemon_running

        return is_treasury_daemon_running()
    except Exception:
        return False


def poll_treasury_payments(
    cycle_id: int,
    on_payment: Optional[Callable[[Dict[str, Any]], None]] = None,
    factory_state: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Drain treasury daemon inbox, optionally short inline WS poll, then ingest revenue.
    Never blocks the cycle when daemon is active (permanent unblock).
    """
    address = FACTORY_TREASURY_ADDRESS or FACTORY_XRPL_ADDRESS
    if not address:
        print("[TreasuryMonitor] No treasury address configured.")
        return {"ws_observed": 0, "ingested": [], "treasury_address": None}

    captured: List[Dict[str, Any]] = []
    ws_observed = 0
    poll_mode = "inline_ws"

    if os.getenv("TREASURY_DAEMON_ENABLED", "true").lower() in {"1", "true", "yes"}:
        from observability.treasury_daemon import drain_inbox, start_treasury_daemon

        start_treasury_daemon(address)
        for entry in drain_inbox():
            payment = entry.get("payment")
            if payment:
                captured.append(payment)
                if on_payment:
                    on_payment(payment)

        if SKIP_INLINE_WS and _daemon_active():
            poll_mode = "daemon_inbox_only"
            if os.getenv("XRPL_WS_QUIET", "true").lower() not in {"1", "true", "yes"}:
                print("[TreasuryMonitor] Daemon active — skipping inline WS (inbox drain only)")
        else:
            poll_mode = "daemon_plus_inline"

    if poll_mode != "daemon_inbox_only":

        def _callback(tx: Dict[str, Any]) -> None:
            captured.append(tx)
            if on_payment:
                on_payment(tx)
            print(f"[TreasuryMonitor] Inbound payment detected: {tx.get('tx_hash')}")

        from tools.xrpl_tools import monitor_incoming_payments

        # Prefer public revenue network for inline poll; default testnet for ops
        try:
            from factory_core.xrpl_network import resolve_public_treasury, revenue_network

            pub_addr, pub_net = resolve_public_treasury()
            poll_addr = pub_addr or address
            poll_testnet = pub_net != "mainnet"
        except Exception:
            poll_addr = address
            poll_testnet = True

        ws_observed = monitor_incoming_payments(
            address=poll_addr,
            callback=_callback,
            testnet=poll_testnet,
            timeout_seconds=MONITOR_TIMEOUT,
        )

    try:
        ingest_result = ingest_verified_xrpl_revenue(
            cycle_id=cycle_id,
            treasury_address=address,
            factory_state=factory_state,
        )
    except Exception as exc:
        print(f"[TreasuryMonitor] Ingest error (non-fatal): {exc}")
        ingest_result = {"ingested": [], "unmatched": [], "reconciled": [], "error": str(exc)}
    ingested = ingest_result.get("ingested", [])
    unmatched = ingest_result.get("unmatched", [])

    if factory_state is not None:
        verified_hash = None
        if ingested:
            verified_hash = ingested[-1].get("xrpl_tx_hash")
        factory_state.set_treasury_watermark(
            last_ingested_tx_hash=verified_hash,
            last_poll_at=cycle_id,
        )

    return {
        "ws_observed": ws_observed,
        "ws_captured": captured,
        "ingested": ingested,
        "unmatched": unmatched,
        "treasury_address": address,
        "poll_mode": poll_mode,
        "inbox_drained": len(captured),
    }