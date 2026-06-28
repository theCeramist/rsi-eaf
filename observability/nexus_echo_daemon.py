"""
Nexus echo daemon — detect jarvis-swarm / aetherforge drift vs factory cycles.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from config.integration import AETHERFORGE_URL, NEXUS_OWNER, NEXUS_REPO

_stop = threading.Event()
_thread: Optional[threading.Thread] = None


def _interval_sec() -> float:
    return float(os.getenv("NEXUS_ECHO_INTERVAL_SEC", "420"))


def _drift_threshold() -> int:
    return int(os.getenv("NEXUS_ECHO_DRIFT_CYCLES", "3"))


def check_nexus_drift() -> Dict[str, Any]:
    from factory_core.state import FactoryState
    from tools.github_client import fetch_repo_json
    from tools.nexus_bridge import verify_external_surfaces
    from tools.publish_tools import verify_live_url

    factory_cycle = FactoryState().current_cycle
    control = fetch_repo_json(NEXUS_OWNER, NEXUS_REPO, "control-state.json") or {}
    runner = control.get("rsi_eaf_runner", {})
    nexus_cycle = int(runner.get("cycle_id") or 0)
    drift = factory_cycle - nexus_cycle if nexus_cycle else factory_cycle

    surfaces = verify_external_surfaces()
    aetherforge_ok = verify_live_url(AETHERFORGE_URL)

    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "factory_cycle": factory_cycle,
        "nexus_cycle": nexus_cycle,
        "drift_cycles": drift,
        "aetherforge_ok": aetherforge_ok,
        "surfaces": surfaces,
        "needs_emit": drift >= _drift_threshold(),
    }
    return result


def run_echo_tick(repair: bool = True) -> Dict[str, Any]:
    check = check_nexus_drift()
    repair_result: Dict[str, Any] = {}
    if repair and check.get("needs_emit"):
        from tools.jarvis_swarm_ci_repair import maybe_repair_nexus_ci

        repair_result["ci"] = maybe_repair_nexus_ci(int(check.get("factory_cycle", 0)), force=False)
    check["repair"] = repair_result
    return check


def _daemon_loop() -> None:
    while not _stop.is_set():
        try:
            tick = run_echo_tick(repair=True)
            from observability.daemon_supervisor import heartbeat

            heartbeat(
                "nexus_echo",
                {
                    "drift_cycles": tick.get("drift_cycles"),
                    "needs_emit": tick.get("needs_emit"),
                    "aetherforge_ok": tick.get("aetherforge_ok"),
                },
            )
        except Exception as exc:
            from observability.daemon_supervisor import heartbeat

            heartbeat("nexus_echo", {"error": str(exc)})
        if _stop.wait(_interval_sec()):
            break


def start_nexus_echo_daemon() -> Dict[str, Any]:
    global _thread
    if os.getenv("NEXUS_ECHO_DAEMON_ENABLED", "true").lower() not in {"1", "true", "yes"}:
        return {"started": False, "reason": "disabled"}
    if _thread and _thread.is_alive():
        return {"started": True, "reason": "already_running", "interval_sec": _interval_sec()}
    _stop.clear()
    _thread = threading.Thread(target=_daemon_loop, name="nexus-echo-daemon", daemon=True)
    _thread.start()
    return {"started": True, "interval_sec": _interval_sec(), "drift_threshold": _drift_threshold()}


def stop_nexus_echo_daemon() -> None:
    _stop.set()