"""
Executable evolution — deterministic actions + optional Grok Build for stale proposals.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from factory_core.grok_cli import run_evolution_task
from factory_core.stale_evolution import filter_stale_proposals, resolve_stale_proposals
from observability.economic_ledger import ledger

EXECUTE_EVOLUTION = os.getenv("EXECUTE_EVOLUTION", "true").lower() in {"1", "true", "yes"}
GROK_EVOLUTION_TIMEOUT = int(os.getenv("GROK_EVOLUTION_TIMEOUT_SEC", "120"))
EVOLUTION_LOG = Path(os.getenv("EVOLUTION_EXEC_LOG", "factory_core/evolution_executions.jsonl"))

_STALE_ACTION_MAP = {
    "refresh_tip_surfaces": "refresh live tip surfaces on vercel",
    "accelerate_treasury_surfaces": "accelerate treasury-visible payment surfaces",
    "treasury_ingest_github": "treasury ingest + github issue refresh",
    "harden_payment_intent": "harden payment_intent ingest paths",
    "tool_analytics": "extend tool_improvements.jsonl analytics",
    "batch_vercel_deploy": "batch vercel deploy once per cycle",
}


def _order_stale_by_director(stale: List[str], priorities: List[str]) -> List[str]:
    """Reorder stale titles to match director evolution priority."""
    if not priorities:
        return stale
    rank = {title: i for i, title in enumerate(stale)}

    def sort_key(title: str) -> tuple[int, int]:
        normalized = title.lower()
        for action in priorities:
            mapped = _STALE_ACTION_MAP.get(action, "")
            if mapped and mapped in normalized:
                return (priorities.index(action), rank.get(title, 999))
        return (len(priorities), rank.get(title, 999))

    return sorted(stale, key=sort_key)


def _append_log(entry: Dict[str, Any]) -> None:
    EVOLUTION_LOG.parent.mkdir(parents=True, exist_ok=True)
    with EVOLUTION_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")


def _run_grok_task(cycle_id: int, task: str) -> Dict[str, Any]:
    if not EXECUTE_EVOLUTION:
        return {"skipped": True, "reason": "execute_evolution_disabled"}
    return run_evolution_task(cycle_id, task, timeout=GROK_EVOLUTION_TIMEOUT)


def _pick_evolution_task(
    proposals: List[Dict[str, Any]],
    rsi_meta: Dict[str, Any],
    execution_result: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    focus = rsi_meta.get("focus", "revenue")
    stale = rsi_meta.get("stale_proposals", [])

    for proposal in proposals:
        if proposal.get("source") == "self_improvement" and stale:
            return {
                "action": "break_stale_proposal_cycle",
                "proposal": proposal,
                "detail": stale[0],
            }
        if proposal.get("source") == "revenue_goal" and "GitHub" in proposal.get("title", ""):
            return {"action": "github_distribution", "proposal": proposal}

    if focus == "tools":
        return {
            "action": "grok_tool_hardening",
            "task": "Harden treasury ingest retries and canonical tip URL handling.",
        }
    if focus == "rsi":
        return {
            "action": "grok_rsi_meta",
            "task": "Reduce proposal duplication in factory_core/proposer.py rule outputs.",
        }
    if execution_result.get("treasury_unmatched_inflows", 0) > 0:
        return {
            "action": "grok_payment_friction",
            "task": "Improve payment_intent matching for unmatched treasury inflows.",
        }
    return None


def execute_evolution(
    cycle_id: int,
    proposals: List[Dict[str, Any]],
    gate_result: Dict[str, Any],
    rsi_meta: Dict[str, Any],
    execution_result: Dict[str, Any],
    featured: Optional[Dict[str, str]] = None,
    treasury_address: str = "",
    factory_state: Optional[Any] = None,
) -> Dict[str, Any]:
    """Run one executable evolution action when gates pass."""
    from gates.verifier import gates_evolution_allowed

    if not gates_evolution_allowed(gate_result):
        return {"executed": False, "reason": "gates_failed", "failed": gate_result.get("failed_gates")}

    actions: List[Dict[str, Any]] = []
    task = _pick_evolution_task(proposals, rsi_meta, execution_result)

    stale = filter_stale_proposals(
        rsi_meta.get("stale_proposals", []),
        factory_state=factory_state,
    )
    focus = rsi_meta.get("focus", "revenue")

    director_priorities = [
        p.strip()
        for p in os.getenv("DIRECTOR_EVOLUTION_PRIORITIES", "").split(",")
        if p.strip()
    ]
    if not director_priorities:
        from factory_core.director import director as factory_director

        director_priorities = factory_director._evolution_priorities(
            focus=focus,
            stale=stale,
            execution=execution_result,
            gates_passed=True,
        )

    if stale:
        ordered_stale = _order_stale_by_director(stale, director_priorities)
        stale_actions = resolve_stale_proposals(
            ordered_stale,
            cycle_id=cycle_id,
            execution_result=execution_result,
            treasury_address=treasury_address,
            featured=featured,
            factory_state=factory_state,
            max_actions=min(3, len(director_priorities) or 2),
        )
        actions.extend(stale_actions)

    for priority in director_priorities:
        if any(a.get("action") == priority for a in actions):
            continue
        if priority == "accelerate_treasury_surfaces":
            from tools.revenue_acceleration import accelerate_treasury_surfaces

            accel = accelerate_treasury_surfaces(
                cycle_id=cycle_id,
                treasury_address=treasury_address,
                featured=featured or execution_result.get("featured_surfaces", {}),
                factory_state=factory_state,
            )
            if factory_state and accel.get("implemented"):
                factory_state.mark_proposal_implemented(
                    "Accelerate treasury-visible payment surfaces"
                )
            actions.append(accel)

    force_github = os.getenv("DIRECTOR_FORCE_GITHUB", "").lower() in {"1", "true", "yes"}
    if stale or focus == "revenue" or force_github:
        execution_result["force_distribution"] = True

    grok_task = None
    if task:
        if task.get("action") == "grok_tool_hardening":
            grok_task = task.get("task")
        elif task.get("action") == "grok_rsi_meta":
            grok_task = task.get("task")
        elif task.get("action") == "grok_payment_friction":
            grok_task = task.get("task")
        elif task.get("action") == "break_stale_proposal_cycle" and focus in ("tools", "rsi"):
            unresolved = filter_stale_proposals(stale, factory_state=factory_state)
            if unresolved:
                grok_task = f"Resolve stale proposal: {unresolved[0][:200]}"

    allow_grok = os.getenv("DIRECTOR_ALLOW_GROK_EVOLUTION", "false").lower() in {
        "1",
        "true",
        "yes",
    }
    if grok_task and allow_grok:
        grok_result = _run_grok_task(cycle_id, grok_task)
        actions.append({"action": "grok_build", "task": grok_task, **grok_result})

    unmatched = int(execution_result.get("treasury_unmatched_inflows", 0) or 0)
    if unmatched > 0 or focus == "revenue":
        from tools.github_semantic_triage import triage_payment_friction

        triage = triage_payment_friction()
        if triage.get("friction_detected"):
            actions.append({"action": "github_payment_triage", **triage})

    if os.getenv("EVOLUTION_VIA_PR", "false").lower() in {"1", "true", "yes"} and grok_task:
        from tools.github_pr_workflow import evolution_pr_flow

        pr_flow = evolution_pr_flow(
            cycle_id,
            files=[{"path": "factory_core/evolution_note.txt", "content": grok_task}],
            task_summary=grok_task,
        )
        actions.append({"action": "evolution_pr", **pr_flow})

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "cycle_id": cycle_id,
        "focus": focus,
        "actions": actions,
        "stale_proposals": stale[:3],
    }
    _append_log(entry)

    if actions:
        ledger.log_event(
            event_type="milestone",
            source="evolution_executor",
            amount_usd_est=0.0,
            cycle_id=cycle_id,
            metadata={"phase": "execute_evolution", **entry},
            anchor_to_xrpl=False,
        )

    return {
        "executed": bool(actions),
        "actions": actions,
        "focus": focus,
    }