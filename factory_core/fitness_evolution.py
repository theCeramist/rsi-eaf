"""
Fitness-driven evolution — priorities keyed to Agents.md primary goal score.

When composite fitness is failing, evolution MUST target revenue capture,
not RSI meta-loops or surface-only deploys.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

FITNESS_FAIL_THRESHOLD = float(os.getenv("FITNESS_FAIL_THRESHOLD", "60"))
FITNESS_CRITICAL_THRESHOLD = float(os.getenv("FITNESS_CRITICAL_THRESHOLD", "25"))


def load_fitness_report(cycle_id: int = 0) -> Dict[str, Any]:
    try:
        from observability.factory_fitness_report import generate_factory_fitness_report

        return generate_factory_fitness_report(cycle_id=cycle_id)
    except Exception as exc:
        return {"composite_score": 0, "verdict": "failing", "error": str(exc)}


def fitness_is_failing(report: Optional[Dict[str, Any]] = None) -> bool:
    report = report or load_fitness_report()
    return float(report.get("composite_score", 0)) < FITNESS_FAIL_THRESHOLD


def fitness_focus(
    report: Optional[Dict[str, Any]] = None,
    analysis_focus: str = "revenue",
) -> str:
    """Override cycle focus when primary goal is failing."""
    if fitness_is_failing(report):
        return "revenue"
    return analysis_focus


def fitness_evolution_priorities(
    *,
    report: Optional[Dict[str, Any]] = None,
    execution: Optional[Dict[str, Any]] = None,
    gates: Optional[Dict[str, Any]] = None,
    stale: Optional[List[str]] = None,
) -> List[str]:
    """
    Ordered evolution action keys — highest fitness ROI first.

    Maps fitness gaps → deterministic evolution_executor priorities.
    """
    report = report or load_fitness_report()
    execution = execution or {}
    gates = gates or {}
    stale = stale or []
    score = float(report.get("composite_score", 0))
    economics = report.get("economics") or {}
    verified = int(economics.get("verified_revenue_events", 0) or 0)
    organic = float(economics.get("organic_revenue_usd_est", 0) or 0)

    evolution_meta = (report.get("actions") or {}).get("evolution") or {}
    mainnet = report.get("mainnet") or {}
    gate_trends = (mainnet.get("metrics") or {}).get("gate_trends") or {}
    raw_failures = evolution_meta.get("top_gate_failures") or gate_trends.get("top_failures") or []
    top_failures = dict(raw_failures)

    priorities: List[str] = []

    if score < FITNESS_FAIL_THRESHOLD:
        if verified == 0 or organic <= 0:
            priorities.extend(
                [
                    "fitness_revenue_capture",
                    "treasury_ingest_github",
                    "accelerate_treasury_surfaces",
                ]
            )
        if top_failures.get("live_url_reachable", 0) > 0:
            priorities.extend(["batch_vercel_deploy", "refresh_tip_surfaces"])
        if int(execution.get("treasury_unmatched_inflows", 0) or 0) > 0:
            priorities.append("grok_payment_friction")

    for title in stale:
        lower = title.lower()
        if "verified_revenue" in lower or "treasury ingest" in lower:
            if "fitness_revenue_capture" not in priorities:
                priorities.insert(0, "fitness_revenue_capture")
        elif "live tip" in lower or "live_url" in lower:
            priorities.append("refresh_tip_surfaces")
        elif "batch vercel" in lower:
            priorities.append("batch_vercel_deploy")

    if score >= FITNESS_FAIL_THRESHOLD and not priorities:
        return []

    seen: set[str] = set()
    ordered: List[str] = []
    for item in priorities:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered[:4]


def fitness_allow_grok_evolution(
    report: Optional[Dict[str, Any]] = None,
    *,
    gates_core_passed: bool = False,
    budget_ok: bool = True,
    unmatched: bool = False,
) -> bool:
    """Grok evolution only when fitness-critical AND revenue-friction signals exist."""
    if not budget_ok or not gates_core_passed:
        return False
    report = report or load_fitness_report()
    if float(report.get("composite_score", 0)) >= FITNESS_FAIL_THRESHOLD:
        return False
    economics = report.get("economics") or {}
    if int(economics.get("verified_revenue_events", 0) or 0) > 0:
        return False
    return unmatched or os.getenv("FITNESS_GROK_ON_CAPTURE", "false").lower() in {
        "1",
        "true",
        "yes",
    }


def apply_fitness_env(report: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Push fitness mode into process env for cycle_runner / evolution."""
    report = report or load_fitness_report()
    failing = fitness_is_failing(report)
    os.environ["DIRECTOR_FITNESS_MODE"] = "true" if failing else "false"
    if failing:
        os.environ["CYCLE_FOCUS"] = "revenue"
        os.environ["REVENUE_PURSUIT"] = "true"
    return {
        "fitness_mode": failing,
        "composite_score": report.get("composite_score"),
        "priorities": fitness_evolution_priorities(report=report) if failing else [],
    }