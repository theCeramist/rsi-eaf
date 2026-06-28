"""
Parallel lanes coordinator — daemons, async Grok tasks, post-cycle dispatch.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional


def start_all_parallel_infrastructure(treasury_address: Optional[str] = None) -> List[Dict[str, Any]]:
    """Boot all enabled daemons via daemon_supervisor."""
    from observability.daemon_supervisor import register_daemon, start_factory_daemons

    results = start_factory_daemons(treasury_address)

    daemon_specs = [
        ("distribution", "DISTRIBUTION_DAEMON_ENABLED", "observability.distribution_daemon", "start_distribution_daemon"),
        ("xrpl_intel", "XRPL_INTEL_DAEMON_ENABLED", "observability.xrpl_intel_daemon", "start_xrpl_intel_daemon"),
        ("nexus_echo", "NEXUS_ECHO_DAEMON_ENABLED", "observability.nexus_echo_daemon", "start_nexus_echo_daemon"),
        ("ci_babysitter", "CI_BABYSITTER_ENABLED", "observability.ci_babysitter_daemon", "start_ci_babysitter_daemon"),
    ]
    for name, env_key, module, fn_name in daemon_specs:
        if os.getenv(env_key, "true").lower() not in {"1", "true", "yes"}:
            continue
        import importlib

        mod = importlib.import_module(module)
        start_fn = getattr(mod, fn_name)
        results.append(register_daemon(name, start_fn))

    return results


def run_post_analyze_lanes(
    cycle_id: int,
    analysis: Dict[str, Any],
    featured: Optional[Dict[str, Any]] = None,
    consecutive_zero_revenue: int = 0,
) -> Dict[str, Any]:
    """Lanes that run after Analyze when organic revenue is stressed."""
    lanes: Dict[str, Any] = {}
    organic = float(analysis.get("net_cumulative", {}).get("organic_revenue_usd_est", 0) or 0)

    from factory_core.revenue_sprint import run_revenue_sprint, should_run_revenue_sprint

    if should_run_revenue_sprint(organic, consecutive_zero_revenue):
        lanes["revenue_sprint"] = run_revenue_sprint(cycle_id, analysis, featured)

    from factory_core.micro_saas_scout import run_micro_saas_scout, should_run_scout

    if should_run_scout(cycle_id):
        intel = {}
        try:
            from observability.xrpl_intel_daemon import latest_intel

            intel = latest_intel()
        except Exception:
            pass
        lanes["micro_saas_scout"] = run_micro_saas_scout(cycle_id, intel)

    return lanes


def run_post_evolve_lanes(
    cycle_id: int,
    evolution: Dict[str, Any],
    gate_result: Dict[str, Any],
    featured: Optional[Dict[str, str]] = None,
    allow_code_evolution: bool = False,
) -> Dict[str, Any]:
    """Verifier + optional best-of-N after Evolve."""
    lanes: Dict[str, Any] = {}

    from factory_core.verifier_subagent import run_worktree_verifier

    lanes["worktree_verifier"] = run_worktree_verifier(cycle_id, evolution, gate_result, featured)

    if allow_code_evolution and evolution.get("executor", {}).get("executed"):
        executor = evolution.get("executor", {})
        actions = executor.get("actions") or []
        for action in actions:
            task = action.get("action") or action.get("proposal")
            if not task or action.get("implemented") is False:
                continue
            if os.getenv("BEST_OF_N_ON_EVOLUTION", "false").lower() in {"1", "true", "yes"}:
                from factory_core.best_of_n_evolve import run_best_of_n_evolution

                lanes["best_of_n"] = run_best_of_n_evolution(cycle_id, str(task))
            break

    return lanes


def dispatch_post_cycle_async(
    cycle_id: int,
    cycle_result: Dict[str, Any],
    factory_state: Optional[Any] = None,
) -> Dict[str, Any]:
    """ACP lane + nexus echo tick after cycle completes."""
    lanes: Dict[str, Any] = {}
    from factory_core.acp_lane import maybe_dispatch_acp_post_cycle

    lanes["acp"] = maybe_dispatch_acp_post_cycle(cycle_id, cycle_result, factory_state)

    if os.getenv("NEXUS_ECHO_POST_CYCLE", "true").lower() in {"1", "true", "yes"}:
        try:
            from observability.nexus_echo_daemon import run_echo_tick

            lanes["nexus_echo_tick"] = run_echo_tick(repair=True)
            tick = lanes["nexus_echo_tick"]
            if tick.get("needs_emit") and not tick.get("repair", {}).get("nexus_emit", {}).get("emitted"):
                from tools.nexus_bridge import force_nexus_emit_from_state

                lanes["nexus_force_emit"] = force_nexus_emit_from_state(factory_state)
        except Exception as exc:
            lanes["nexus_echo_tick"] = {"error": str(exc)}

    return lanes