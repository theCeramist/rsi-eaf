"""
Controlled evolution — git commit milestone when gates pass.
"""

import json
import os
import subprocess
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from observability.economic_ledger import ledger


def evolve_cycle(
    cycle_id: int,
    gate_result: Dict[str, Any],
    analysis: Dict[str, Any],
    proposals: list,
) -> Dict[str, Any]:
    """
    Log evolution milestone. Optionally git-commit if repo exists and gates passed.
    Does not auto-apply code changes — surgical human/grok review still required.
    """
    from gates.verifier import gates_evolution_allowed

    if not gates_evolution_allowed(gate_result):
        return {
            "evolved": False,
            "reason": "gates_failed",
            "gate_result": gate_result,
        }

    metadata = {
        "cycle_id": cycle_id,
        "gates": gate_result,
        "analysis_summary": {
            "net": analysis.get("net_this_cycle"),
            "bottlenecks": analysis.get("bottlenecks"),
        },
        "proposals_count": len(proposals),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    event = ledger.log_event(
        event_type="milestone",
        source="evolver",
        amount_usd_est=0.0,
        cycle_id=cycle_id,
        metadata={"phase": "evolve", **metadata},
        anchor_to_xrpl=False,
    )

    git_result = _try_git_snapshot(cycle_id, gate_result)
    return {
        "evolved": True,
        "ledger_event": event,
        "git": git_result,
        "note": "Evolution logged; code changes require reviewed grok build execution.",
    }


def _try_git_snapshot(cycle_id: int, gate_result: Dict[str, Any]) -> Dict[str, Any]:
    if not os.path.exists(".git"):
        return {"skipped": True, "reason": "no_git_repo"}

    try:
        subprocess.run(["git", "add", "-A"], check=False, capture_output=True)
        msg = f"cycle-{cycle_id} snapshot (gates {gate_result.get('passed_count')}/{gate_result.get('total_count')})"
        commit = subprocess.run(
            ["git", "commit", "-m", msg, "--allow-empty"],
            capture_output=True,
            text=True,
            check=False,
        )
        return {
            "committed": commit.returncode == 0,
            "message": msg,
            "output": (commit.stdout or commit.stderr or "")[-300:],
        }
    except OSError as exc:
        return {"error": str(exc)}