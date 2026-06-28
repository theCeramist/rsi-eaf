"""
Distribution/outreach daemon — promote treasury surfaces between factory cycles.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

INTEL_FILE = Path(os.getenv("DISTRIBUTION_DAEMON_LOG", "observability/distribution_daemon.jsonl"))
_stop = threading.Event()
_thread: Optional[threading.Thread] = None
_last_cycle = 0
_tip_dead_ticks = 0


def _interval_sec() -> float:
    return float(os.getenv("DISTRIBUTION_DAEMON_INTERVAL_SEC", "300"))


def _current_cycle() -> int:
    try:
        from factory_core.state import FactoryState

        return FactoryState().current_cycle
    except Exception:
        return 0


def run_distribution_tick(cycle_id: Optional[int] = None, force: bool = False) -> Dict[str, Any]:
    """One outreach/distribution promotion pass."""
    from revenue_engines.base_engine import resolve_treasury
    from tools.distribution_tools import canonical_tip_url, featured_links_for_index
    from tools.github_distribution import maybe_push_distribution, refresh_support_issue
    from tools.publish_tools import verify_live_url
    from tools.revenue_acceleration import write_outreach_bundle

    cycle_id = cycle_id or _current_cycle() or 1
    treasury = resolve_treasury()
    featured = featured_links_for_index(cycle_id)
    outreach = write_outreach_bundle(cycle_id, treasury, featured)

    tip_url = outreach.get("tip_url") or canonical_tip_url(cycle_id)
    tip_live = verify_live_url(tip_url) if tip_url else False

    global _tip_dead_ticks
    deploy_result: Dict[str, Any] = {}
    force_deploy_threshold = int(os.getenv("DISTRIBUTION_FORCE_DEPLOY_TICKS", "2"))
    if not tip_live:
        _tip_dead_ticks += 1
        if _tip_dead_ticks >= force_deploy_threshold or force:
            from tools.publish_tools import deploy_to_vercel, reset_cycle_deploy_flag

            reset_cycle_deploy_flag()
            deploy_result = deploy_to_vercel(force=force or _tip_dead_ticks >= force_deploy_threshold)
            if deploy_result.get("success"):
                tip_url = canonical_tip_url(cycle_id) or tip_url
                tip_live = verify_live_url(tip_url) if tip_url else False
                _tip_dead_ticks = 0
    else:
        _tip_dead_ticks = 0

    issue = refresh_support_issue(cycle_id, featured, treasury)
    dist = maybe_push_distribution(
        cycle_id=cycle_id,
        featured=featured,
        treasury_address=treasury,
        force=force,
    )

    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "cycle_id": cycle_id,
        "tip_url": tip_url,
        "tip_live": tip_live,
        "issue_updated": issue.get("issue_updated"),
        "distribution_pushed": dist.get("pushed"),
        "force": force,
        "vercel_deploy": deploy_result or None,
    }
    INTEL_FILE.parent.mkdir(parents=True, exist_ok=True)
    with INTEL_FILE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")

    return {"started": True, "tick": record, "outreach": outreach, "distribution": dist, "issue": issue}


def _daemon_loop() -> None:
    global _last_cycle
    while not _stop.is_set():
        try:
            cycle = _current_cycle()
            force = cycle != _last_cycle and cycle > 0
            result = run_distribution_tick(cycle_id=cycle, force=force)
            _last_cycle = cycle
            from observability.daemon_supervisor import heartbeat

            heartbeat("distribution", {"last_tick": result.get("tick")})
        except Exception as exc:
            from observability.daemon_supervisor import heartbeat

            heartbeat("distribution", {"error": str(exc)})
        if _stop.wait(_interval_sec()):
            break


def start_distribution_daemon() -> Dict[str, Any]:
    global _thread
    if os.getenv("DISTRIBUTION_DAEMON_ENABLED", "true").lower() not in {"1", "true", "yes"}:
        return {"started": False, "reason": "disabled"}
    if _thread and _thread.is_alive():
        return {"started": True, "reason": "already_running", "interval_sec": _interval_sec()}
    _stop.clear()
    _thread = threading.Thread(target=_daemon_loop, name="distribution-daemon", daemon=True)
    _thread.start()
    return {"started": True, "interval_sec": _interval_sec()}


def stop_distribution_daemon() -> None:
    _stop.set()