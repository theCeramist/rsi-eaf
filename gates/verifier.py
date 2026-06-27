"""
Verification gates for RSI-EAF cycles.
All gates must pass before evolution (Phase 6).
"""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from observability.economic_ledger import ledger
from tools.publish_tools import verify_live_url
from tools.xrpl_tools import get_client

PUBLISHED_DIR = os.getenv("PUBLISHED_DIR", "published")


def _gate(name: str, passed: bool, detail: str) -> Dict[str, Any]:
    return {"gate": name, "passed": passed, "detail": detail}


def verify_xrpl_transaction(tx_hash: str, testnet: bool = True) -> bool:
    if not tx_hash:
        return False
    try:
        from xrpl.models.requests import Tx

        client = get_client(testnet)
        response = client.request(Tx(transaction=tx_hash))
        result = response.result
        return bool(result.get("validated") or result.get("meta", {}).get("TransactionResult") == "tesSUCCESS")
    except Exception:
        return False


def run_cycle_gates(
    cycle_id: int,
    execution_result: Dict[str, Any],
    require_live_url: bool = False,
) -> Dict[str, Any]:
    """Run all mandatory gates for a completed cycle."""
    gates: List[Dict[str, Any]] = []

    published_list = execution_result.get("published_assets") or []
    if not published_list and execution_result.get("published_asset"):
        published_list = [execution_result["published_asset"]]
    published_exists = any(p and Path(p).exists() for p in published_list)
    gates.append(
        _gate(
            "published_asset_exists",
            published_exists,
            f"count={len(published_list)} paths={published_list[:3]}",
        )
    )

    tx_hash = execution_result.get("xrpl_tx_hash")
    tx_ok = verify_xrpl_transaction(tx_hash) if tx_hash else False
    gates.append(
        _gate(
            "xrpl_anchor_confirmed",
            tx_ok,
            f"tx_hash={tx_hash}",
        )
    )

    cycle_events = [e for e in ledger.get_recent_events(200) if e.get("cycle_id") == cycle_id]
    cost_logged = any(e.get("event_type") == "cost" for e in cycle_events)
    gates.append(
        _gate(
            "cycle_cost_logged",
            cost_logged,
            f"cost_events={sum(1 for e in cycle_events if e.get('event_type') == 'cost')}",
        )
    )

    live_url = execution_result.get("live_url")
    live_ok = True
    if live_url:
        live_ok = verify_live_url(live_url)
        gates.append(_gate("live_url_reachable", live_ok, live_url))
    elif require_live_url:
        gates.append(_gate("live_url_reachable", False, "no live_url in execution result"))
        live_ok = False

    net = ledger.calculate_net(since_cycle=cycle_id)
    gates.append(
        _gate(
            "ledger_net_computable",
            "net_usd_est" in net,
            str(net),
        )
    )

    all_passed = all(g["passed"] for g in gates)
    return {
        "cycle_id": cycle_id,
        "all_passed": all_passed,
        "gates": gates,
        "passed_count": sum(1 for g in gates if g["passed"]),
        "total_count": len(gates),
    }