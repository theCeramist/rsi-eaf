"""
ACP orchestration lane — meta-evolution and analysis off the hot cycle path.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

LANE_LOG = Path(os.getenv("ACP_LANE_LOG", "observability/acp_lane.jsonl"))
_pending: Dict[int, Dict[str, Any]] = {}
_lock = threading.Lock()


def enqueue_acp_task(cycle_id: int, task_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    with _lock:
        _pending[cycle_id] = {"task_type": task_type, "payload": payload, "enqueued_at": datetime.now(timezone.utc).isoformat()}
    return {"enqueued": True, "cycle_id": cycle_id, "task_type": task_type}


def run_acp_lane_task(
    cycle_id: int,
    task_type: str,
    payload: Dict[str, Any],
    factory_state: Optional[Any] = None,
) -> Dict[str, Any]:
    """Execute one ACP lane task (meta-evolution, triage, analysis)."""
    if os.getenv("ACP_LANE_ENABLED", "true").lower() not in {"1", "true", "yes"}:
        return {"skipped": True, "reason": "ACP_LANE disabled"}

    from factory_core.grok_acp import run_cycle_via_acp

    prompts = {
        "meta_evolution": (
            f"RSI-EAF cycle {cycle_id} meta-evolution (ACP lane).\n"
            f"Payload: {json.dumps(payload, default=str)[:5000]}\n"
            "Propose ONE surgical factory improvement with expected economic delta. "
            "Do not apply edits — plan only. Return JSON proposals array."
        ),
        "github_triage": (
            f"RSI-EAF cycle {cycle_id} GitHub semantic triage.\n"
            f"Context: {json.dumps(payload, default=str)[:3000]}\n"
            "Summarize actionable issues for revenue surfaces. Read-only."
        ),
        "post_cycle_analysis": (
            f"RSI-EAF cycle {cycle_id} post-cycle ACP analysis.\n"
            f"Result: {json.dumps(payload, default=str)[:6000]}\n"
            'Return JSON: {"observation":"","revenue_action":"","risk":""}'
        ),
    }
    prompt = prompts.get(task_type, prompts["post_cycle_analysis"])
    result = run_cycle_via_acp(cycle_id, prompt, factory_state=factory_state)

    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "cycle_id": cycle_id,
        "task_type": task_type,
        "result": {k: v for k, v in result.items() if k != "result"},
    }
    LANE_LOG.parent.mkdir(parents=True, exist_ok=True)
    with LANE_LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, default=str) + "\n")
    with _lock:
        _pending.pop(cycle_id, None)
    return {"lane": "acp", **record}


def maybe_dispatch_acp_post_cycle(
    cycle_id: int,
    cycle_result: Dict[str, Any],
    factory_state: Optional[Any] = None,
) -> Dict[str, Any]:
    """Fire-and-forget ACP post-cycle analysis in background thread."""
    if os.getenv("GROK_ORCHESTRATION", "subprocess").lower() != "acp":
        return {"skipped": True, "reason": "acp_not_primary"}

    def _worker() -> None:
        run_acp_lane_task(cycle_id, "post_cycle_analysis", cycle_result, factory_state)

    thread = threading.Thread(target=_worker, name=f"acp-lane-{cycle_id}", daemon=True)
    thread.start()
    return {"dispatched": True, "cycle_id": cycle_id, "task_type": "post_cycle_analysis"}