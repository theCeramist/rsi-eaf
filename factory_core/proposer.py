"""
Improvement proposals — Grok Build headless + rule-based merge.
"""

import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from factory_core.self_improver import self_improvement_proposals
from factory_core.stale_evolution import BUILTIN_IMPLEMENTED

PROPOSALS_DIR = Path(os.getenv("FACTORY_PROPOSALS_DIR", "factory_core/proposals"))
GROK_BIN = os.getenv("GROK_BIN", shutil.which("grok") or os.path.expanduser("~/.grok/bin/grok.exe"))
PROPOSAL_TIMEOUT = int(os.getenv("GROK_PROPOSAL_TIMEOUT_SEC", "120"))
GROK_PROPOSALS_ENABLED = os.getenv("GROK_PROPOSALS_ENABLED", "true").lower() in {"1", "true", "yes"}


def _rule_based_proposals(analysis: Dict[str, Any]) -> List[Dict[str, Any]]:
    proposals = []
    if "no_verified_revenue" in analysis.get("bottlenecks", []):
        proposals.append({
            "title": "Distribute tip manifest + briefing unlock URLs",
            "impact": "Drive external XRPL payments to treasury via agent-readable manifest",
            "verification": "treasury_monitor ingests payment with type=revenue memo",
            "source": "rule_based",
        })
        proposals.append({
            "title": "Paid briefing unlock campaign",
            "impact": f"Gated intel at ${os.getenv('BRIEFING_UNLOCK_USD', '2.0')} via product_id memo",
            "verification": "briefing_published event shows unlocked=true after external payment",
            "source": "rule_based",
        })
    if not analysis.get("live_url"):
        proposals.append({
            "title": "Reliable Vercel publish pipeline",
            "impact": "Every asset gets a queryable HTTPS URL in ledger metadata",
            "verification": "gate live_url_reachable passes on next cycle",
            "source": "rule_based",
        })
    if not proposals:
        proposals.append({
            "title": "Optimize token burn per cycle",
            "impact": "Reduce grok session costs while maintaining gate pass rate",
            "verification": "cycle_cost_usd decreases with gates still passing",
            "source": "rule_based",
        })
    return proposals


def _tool_improvement_proposals(analysis: Dict[str, Any], cycle_id: int) -> List[Dict[str, Any]]:
    proposals = [
        {
            "title": "Batch Vercel deploy once per cycle",
            "impact": "Cut deploy time and respect 35m cooldown",
            "verification": "deploy_to_vercel skips after first success per cycle",
            "source": "tool_improvement",
        },
        {
            "title": "Harden payment_intent ingest paths",
            "impact": "Reduce unmatched treasury inflows",
            "verification": "pytest payment_intent + revenue_ingest tests pass",
            "source": "tool_improvement",
        },
        {
            "title": "XRPL tool self-check in every tool cycle",
            "impact": "Catch connectivity regressions before revenue runs",
            "verification": "gate xrpl_connectivity passes",
            "source": "tool_improvement",
        },
    ]
    if analysis.get("gates_passed"):
        proposals.append({
            "title": "Extend tool_improvements.jsonl analytics",
            "impact": "Trend pytest duration and XRPL latency across cycles",
            "verification": "tool_improvements_log grows each cycle",
            "source": "tool_improvement",
        })
    return proposals


def _prioritize_by_focus(proposals: List[Dict[str, Any]], focus: str) -> List[Dict[str, Any]]:
    focus_map = {"revenue": "revenue_goal", "tools": "tool_improvement", "rsi": "self_improvement"}
    primary_source = focus_map.get(focus, "")
    primary = [p for p in proposals if p.get("source") == primary_source]
    rest = [p for p in proposals if p.get("source") != primary_source]
    return primary + rest


def _drop_implemented(
    proposals: List[Dict[str, Any]],
    rsi_meta: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    implemented = set(BUILTIN_IMPLEMENTED)
    if rsi_meta:
        for title in rsi_meta.get("implemented_proposals", []):
            implemented.add(title)
    return [p for p in proposals if p.get("title") not in implemented]


def _grok_proposal_prompt(cycle_id: int, analysis: Dict[str, Any], focus: str) -> str:
    return (
        f"RSI-EAF cycle {cycle_id} focus={focus}.\n"
        f"Analysis:\n{json.dumps(analysis, indent=2, default=str)[:8000]}\n\n"
        "Per AGENTS.md propose exactly ONE surgical improvement with:\n"
        "- title, impact (expected economic delta USD), verification (XRPL tx steps), risk\n"
        "Return JSON array with one object. No markdown fences."
    )


def _try_grok_proposals(
    cycle_id: int,
    analysis: Dict[str, Any],
    focus: str,
) -> List[Dict[str, Any]]:
    if not GROK_PROPOSALS_ENABLED or not GROK_BIN or not Path(GROK_BIN).exists():
        return []
    try:
        from factory_core.grok_cli import parse_proposals_from_grok, run_plan_prompt

        grok_result = run_plan_prompt(
            _grok_proposal_prompt(cycle_id, analysis, focus),
            timeout=PROPOSAL_TIMEOUT,
            cycle_id=cycle_id,
        )
        artifact = {
            "cycle_id": cycle_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "grok_build_plan",
            "focus": focus,
            "exit_code": grok_result.get("exit_code"),
            "session_id": grok_result.get("session_id"),
            "output_tail": grok_result.get("output_tail", ""),
            "text": grok_result.get("text", ""),
        }
        PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)
        out_path = PROPOSALS_DIR / f"cycle-{cycle_id}-grok.json"
        out_path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
        proposals = parse_proposals_from_grok(grok_result)
        for p in proposals:
            p.setdefault("source", "grok_build_plan")
            p.setdefault("artifact", str(out_path))
        return proposals
    except (subprocess.TimeoutExpired, OSError) as exc:
        print(f"[Proposer] Grok subprocess failed: {exc}")
        return []


def propose_improvements(
    analysis: Dict[str, Any],
    cycle_id: int,
    rsi_meta: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Generate proposals via Grok headless + rule-based merge."""
    focus = (rsi_meta or {}).get("focus", analysis.get("cycle_focus", "revenue"))
    proposals: List[Dict[str, Any]] = []

    if analysis.get("cycle_mode") in ("tool_improvement", "hybrid"):
        proposals = _tool_improvement_proposals(analysis, cycle_id)
        if analysis.get("cycle_mode") == "hybrid":
            proposals.extend([
                {
                    "title": "Refresh live tip surfaces on Vercel",
                    "impact": "Drive Destination Tag 1 payments to treasury",
                    "verification": "gate live_url_reachable passes after batched deploy",
                    "source": "revenue_goal",
                },
                {
                    "title": "Treasury ingest + GitHub issue refresh",
                    "impact": "Convert inbound XRPL to verified revenue in ledger",
                    "verification": "verified_revenue_events increases on external payment",
                    "source": "revenue_goal",
                },
            ])
        if rsi_meta:
            proposals.extend(self_improvement_proposals(rsi_meta, analysis, cycle_id))
            proposals = _prioritize_by_focus(proposals, focus)
    else:
        proposals = _rule_based_proposals(analysis)
        if rsi_meta:
            proposals.extend(self_improvement_proposals(rsi_meta, analysis, cycle_id))
            proposals = _prioritize_by_focus(proposals, focus)

    grok_proposals = _try_grok_proposals(cycle_id, analysis, focus)
    if grok_proposals:
        proposals = grok_proposals + proposals

    proposals = _drop_implemented(proposals, rsi_meta)
    PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)
    mode = analysis.get("cycle_mode", "revenue")
    suffix = "hybrid" if mode == "hybrid" else ("tools" if mode == "tool_improvement" else "rules")
    out_path = PROPOSALS_DIR / f"cycle-{cycle_id}-{suffix}.json"
    out_path.write_text(json.dumps(proposals, indent=2), encoding="utf-8")
    return proposals