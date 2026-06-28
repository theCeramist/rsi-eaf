"""
CI babysitter daemon — watch rsi-eaf + jarvis-swarm CI and auto-repair.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

LOG_FILE = Path(os.getenv("CI_BABYSITTER_LOG", "observability/ci_babysitter.jsonl"))
_stop = threading.Event()
_thread: Optional[threading.Thread] = None


def _interval_sec() -> float:
    return float(os.getenv("CI_BABYSITTER_INTERVAL_SEC", "900"))


def run_ci_babysitter_tick(cycle_id: int = 0) -> Dict[str, Any]:
    from config.integration import GITHUB_OWNER, GITHUB_REPO, NEXUS_OWNER, NEXUS_REPO
    from tools.github_ci_gate import latest_workflow_run
    from tools.jarvis_swarm_ci_repair import maybe_repair_nexus_ci

    rsi_ci = latest_workflow_run(GITHUB_OWNER, GITHUB_REPO)
    jarvis_ci = latest_workflow_run(NEXUS_OWNER, NEXUS_REPO)

    repair: Dict[str, Any] = {}
    if jarvis_ci.get("conclusion") == "failure" or jarvis_ci.get("blocking"):
        repair = maybe_repair_nexus_ci(cycle_id, force=False)

    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "cycle_id": cycle_id,
        "rsi_eaf_ci": rsi_ci,
        "jarvis_swarm_ci": jarvis_ci,
        "repair": repair,
    }
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, default=str) + "\n")
    return record


def _daemon_loop() -> None:
    while not _stop.is_set():
        try:
            from factory_core.state import FactoryState

            tick = run_ci_babysitter_tick(FactoryState().current_cycle)
            from observability.daemon_supervisor import heartbeat

            heartbeat(
                "ci_babysitter",
                {
                    "rsi_conclusion": tick.get("rsi_eaf_ci", {}).get("conclusion"),
                    "jarvis_conclusion": tick.get("jarvis_swarm_ci", {}).get("conclusion"),
                    "repaired": bool(tick.get("repair", {}).get("success")),
                },
            )
        except Exception as exc:
            from observability.daemon_supervisor import heartbeat

            heartbeat("ci_babysitter", {"error": str(exc)})
        if _stop.wait(_interval_sec()):
            break


def start_ci_babysitter_daemon() -> Dict[str, Any]:
    global _thread
    if os.getenv("CI_BABYSITTER_ENABLED", "true").lower() not in {"1", "true", "yes"}:
        return {"started": False, "reason": "disabled"}
    if _thread and _thread.is_alive():
        return {"started": True, "reason": "already_running", "interval_sec": _interval_sec()}
    _stop.clear()
    _thread = threading.Thread(target=_daemon_loop, name="ci-babysitter-daemon", daemon=True)
    _thread.start()
    return {"started": True, "interval_sec": _interval_sec()}


def stop_ci_babysitter_daemon() -> None:
    _stop.set()