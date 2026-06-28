"""
XRPL market-intelligence daemon — periodic on-chain treasury/factory metrics.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

INTEL_FILE = Path(os.getenv("XRPL_INTEL_FILE", "observability/xrpl_intel.jsonl"))
_latest: Dict[str, Any] = {}
_stop = threading.Event()
_thread: Optional[threading.Thread] = None


def _interval_sec() -> float:
    return float(os.getenv("XRPL_INTEL_INTERVAL_SEC", "600"))


def gather_and_persist(cycle_id: Optional[int] = None) -> Dict[str, Any]:
    from tools.xrpl_research import gather_factory_intel

    cycle_id = cycle_id or 0
    intel = gather_factory_intel(cycle_id)
    intel["timestamp"] = datetime.now(timezone.utc).isoformat()
    INTEL_FILE.parent.mkdir(parents=True, exist_ok=True)
    with INTEL_FILE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(intel) + "\n")
    global _latest
    _latest = intel
    return intel


def latest_intel() -> Dict[str, Any]:
    return dict(_latest)


def _daemon_loop() -> None:
    while not _stop.is_set():
        try:
            from factory_core.state import FactoryState

            cycle = FactoryState().current_cycle
            intel = gather_and_persist(cycle)
            from observability.daemon_supervisor import heartbeat

            heartbeat(
                "xrpl_intel",
                {
                    "treasury_inbound": intel.get("treasury_inbound_payments"),
                    "treasury_balance": intel.get("treasury_balance_xrp"),
                },
            )
        except Exception as exc:
            from observability.daemon_supervisor import heartbeat

            heartbeat("xrpl_intel", {"error": str(exc)})
        if _stop.wait(_interval_sec()):
            break


def start_xrpl_intel_daemon() -> Dict[str, Any]:
    global _thread
    if os.getenv("XRPL_INTEL_DAEMON_ENABLED", "true").lower() not in {"1", "true", "yes"}:
        return {"started": False, "reason": "disabled"}
    if _thread and _thread.is_alive():
        return {"started": True, "reason": "already_running", "interval_sec": _interval_sec()}
    _stop.clear()
    _thread = threading.Thread(target=_daemon_loop, name="xrpl-intel-daemon", daemon=True)
    _thread.start()
    return {"started": True, "interval_sec": _interval_sec()}


def stop_xrpl_intel_daemon() -> None:
    _stop.set()