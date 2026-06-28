"""
Worktree-isolated verifier subagent — pytest + XRPL + live URL checks.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any, Dict, List, Optional

from factory_core.grok_cli import run_headless


def _run_pytest_subset() -> Dict[str, Any]:
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/test_core.py", "-q", "--tb=no"],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
        )
        return {"exit_code": proc.returncode, "passed": proc.returncode == 0, "tail": (proc.stdout or "")[-300:]}
    except (subprocess.TimeoutExpired, OSError) as exc:
        return {"passed": False, "error": str(exc)}


def _verify_xrpl_anchors(cycle_id: int) -> List[Dict[str, Any]]:
    checks: List[Dict[str, Any]] = []
    try:
        from observability.economic_ledger import ledger

        events = ledger.get_recent_events(limit=50)
        for event in events:
            if event.get("cycle_id") != cycle_id:
                continue
            tx_hash = event.get("xrpl_tx_hash")
            if not tx_hash:
                continue
            from gates.verifier import verify_xrpl_transaction

            ok = verify_xrpl_transaction(tx_hash)
            checks.append({"tx_hash": tx_hash, "ok": ok, "source": event.get("source")})
    except Exception as exc:
        checks.append({"error": str(exc)})
    return checks


def _verify_live_surfaces(featured: Optional[Dict[str, str]]) -> Dict[str, Any]:
    from tools.publish_tools import verify_live_url

    featured = featured or {}
    results = {}
    for key in ("tip_page", "canonical_tip_page", "briefing_page", "mythos_page", "micro_tool_page"):
        url = featured.get(key)
        if url:
            results[key] = verify_live_url(url)
    manifest = featured.get("tip_manifest") or featured.get("service_catalog")
    if manifest:
        results["manifest"] = verify_live_url(manifest)
    return results


def run_worktree_verifier(
    cycle_id: int,
    evolution_result: Dict[str, Any],
    gate_result: Dict[str, Any],
    featured: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    Independent verification: local pytest + XRPL tx lookup + Grok read-only review.
    """
    if os.getenv("WORKTREE_VERIFIER_ENABLED", "true").lower() not in {"1", "true", "yes"}:
        return {"skipped": True, "reason": "disabled"}

    pytest_result = _run_pytest_subset()
    xrpl_checks = _verify_xrpl_anchors(cycle_id)
    live_checks = _verify_live_surfaces(featured)

    prompt = (
        f"RSI-EAF cycle {cycle_id} WORKTREE VERIFIER.\n"
        f"pytest_passed={pytest_result.get('passed')}\n"
        f"xrpl_checks={json.dumps(xrpl_checks, default=str)[:2000]}\n"
        f"live_checks={json.dumps(live_checks)}\n"
        f"evolution={json.dumps(evolution_result, default=str)[:3000]}\n"
        f"gates={json.dumps(gate_result, default=str)[:1500]}\n\n"
        "Read-only. Return JSON: "
        '{"approved":bool,"issues":[],"consensus_score":0.0,"xrpl_grounded":bool}'
    )
    grok = run_headless(
        prompt,
        mode="verify",
        max_turns=4,
        worktree=False,
        cycle_id=cycle_id,
    )

    parsed = grok.get("parsed") or {}
    live_ok = all(live_checks.values()) if live_checks else True
    approved = bool(pytest_result.get("passed")) and bool(parsed.get("approved", True)) and live_ok

    return {
        "lane": "worktree_verifier",
        "approved": approved,
        "pytest": pytest_result,
        "xrpl_checks": xrpl_checks,
        "live_checks": live_checks,
        "grok": grok,
        "consensus_score": parsed.get("consensus_score"),
    }