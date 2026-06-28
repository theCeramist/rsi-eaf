"""
FactoryDirector — highest-level cycling agent.

Owns mode, pacing, stop/throttle, focus, and evolution priority decisions.
Runners execute; the director decides what runs next.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from factory_core.economic_guards import (
    REVENUE_TARGET_USD,
    compute_sleep_minutes,
    continuous_run_enabled,
    evaluate_circuit_breakers,
    evaluate_raised_ceiling_revenue_action,
    evaluate_success_stop,
    max_cumulative_net_loss_usd,
)
from factory_core.self_improver import analyze_improvement_history, compute_cycle_focus
from factory_core.stale_evolution import filter_stale_proposals, is_proposal_implemented
from factory_core.state import FactoryState

DECISIONS_LOG = Path(os.getenv("DIRECTOR_DECISIONS_LOG", "factory_core/director_decisions.jsonl"))
MIN_XRP_RESERVE = float(os.getenv("MIN_XRP_RESERVE", "10.0"))
MAX_CONSECUTIVE_NEGATIVE = int(os.getenv("MAX_CONSECUTIVE_NEGATIVE_CYCLES", "5"))


@dataclass
class CyclePlan:
    """Authoritative plan for the next factory cycle."""

    cycle_id_next: int
    mode: str  # hybrid | tool_improvement | revenue
    focus: str  # revenue | tools | rsi
    sleep_minutes: float
    stop_reason: Optional[str] = None
    throttle_from: Optional[str] = None  # prior mode if throttled
    force_github_distribution: bool = False
    force_nexus_emit: bool = False
    evolution_priorities: List[str] = field(default_factory=list)
    allow_grok_evolution: bool = False
    reasoning: Dict[str, Any] = field(default_factory=dict)

    def apply_env(self) -> None:
        """Push plan into process env for cycle_runner / evolution_executor."""
        os.environ["CYCLE_MODE"] = self.mode
        os.environ["CYCLE_FOCUS"] = self.focus
        if self.force_github_distribution:
            os.environ["DIRECTOR_FORCE_GITHUB"] = "true"
        else:
            os.environ.pop("DIRECTOR_FORCE_GITHUB", None)
        if self.force_nexus_emit:
            os.environ["DIRECTOR_FORCE_NEXUS"] = "true"
        else:
            os.environ.pop("DIRECTOR_FORCE_NEXUS", None)
        os.environ["DIRECTOR_ALLOW_GROK_EVOLUTION"] = (
            "true" if self.allow_grok_evolution else "false"
        )
        os.environ["DIRECTOR_EVOLUTION_PRIORITIES"] = ",".join(self.evolution_priorities)


def _append_decision(entry: Dict[str, Any]) -> None:
    DECISIONS_LOG.parent.mkdir(parents=True, exist_ok=True)
    with DECISIONS_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")


class FactoryDirector:
    """Highest-level agent — decides cycling strategy from factory state."""

    def __init__(self) -> None:
        self._meta = analyze_improvement_history()

    def refresh_meta(self) -> None:
        self._meta = analyze_improvement_history()

    def decide_after_cycle(
        self,
        cycle_result: Dict[str, Any],
        *,
        active_mode: str,
        base_interval_minutes: float,
        consecutive_negative: int,
        consecutive_zero_revenue: int,
        consecutive_positive_net: int,
    ) -> CyclePlan:
        """
        Single decision point after a completed cycle.
        Returns plan for the *next* cycle (or stop_reason if factory should halt).
        """
        self.refresh_meta()
        cycle_id = int(cycle_result.get("cycle_id", 0))
        net = cycle_result.get("ledger_net", {})
        analysis = cycle_result.get("analysis", {})
        execution = cycle_result.get("execution", {})
        gates = cycle_result.get("gates", {})
        cycle_revenue = float(analysis.get("cycle_revenue_usd", 0) or 0)
        xrpl_balance = float(cycle_result.get("current_xrp_balance", 0))
        continuous = continuous_run_enabled()

        focus = analysis.get("cycle_focus") or compute_cycle_focus(
            cycle_id, analysis, self._meta
        )
        next_mode = active_mode
        throttle_from: Optional[str] = None
        stop_reason: Optional[str] = None
        reasoning: Dict[str, Any] = {
            "cycle_id": cycle_id,
            "continuous": continuous,
            "cycle_revenue_usd": cycle_revenue,
            "cumulative_net": net.get("net_usd_est"),
            "organic_revenue": net.get("organic_revenue_usd_est"),
            "gates_passed": gates.get("all_passed"),
        }

        breaker_stop, throttle_mode = evaluate_circuit_breakers(
            net, consecutive_zero_revenue, mode=active_mode
        )
        if breaker_stop and not continuous:
            stop_reason = breaker_stop
            reasoning["stop"] = "circuit_breaker"

        if not stop_reason and not continuous:
            raised = evaluate_raised_ceiling_revenue_action(
                net, execution.get("github_distribution")
            )
            if raised:
                stop_reason = raised
                reasoning["stop"] = "raised_ceiling_no_distribution"

        if not stop_reason and not continuous:
            success = evaluate_success_stop(net, consecutive_positive_net)
            if success:
                stop_reason = success
                reasoning["stop"] = "success_target"

        if not stop_reason and xrpl_balance < MIN_XRP_RESERVE:
            stop_reason = f"XRPL balance {xrpl_balance} below reserve {MIN_XRP_RESERVE}"
            reasoning["stop"] = "xrpl_reserve"

        if not stop_reason and consecutive_negative >= MAX_CONSECUTIVE_NEGATIVE:
            stop_reason = f"{MAX_CONSECUTIVE_NEGATIVE} consecutive negative-net cycles"
            reasoning["stop"] = "consecutive_negative"

        if not stop_reason and throttle_mode and active_mode == "hybrid":
            next_mode = throttle_mode
            throttle_from = active_mode
            consecutive_zero_revenue = 0
            reasoning["throttle"] = throttle_mode

        if (
            not stop_reason
            and throttle_mode is None
            and active_mode == "tool_improvement"
            and cycle_revenue > 0
        ):
            next_mode = "hybrid"
            reasoning["resume"] = "revenue_detected"

        revenue_sprint = False
        if not stop_reason and self._should_prioritize_revenue(net, gates, analysis):
            next_mode = "hybrid"
            focus = "revenue"
            revenue_sprint = True
            reasoning["director_override"] = "revenue_gap_critical"

        sleep_min = compute_sleep_minutes(
            base_interval_minutes, cycle_revenue, consecutive_zero_revenue
        )
        if revenue_sprint:
            sleep_min = base_interval_minutes
            reasoning["revenue_sprint_sleep"] = sleep_min

        factory_state = FactoryState()
        stale = filter_stale_proposals(
            self._meta.get("stale_proposals", []),
            factory_state=factory_state,
        )
        evolution_priorities = self._evolution_priorities(
            focus=focus,
            stale=stale,
            execution=execution,
            gates_passed=gates.get("all_passed", False),
            factory_state=factory_state,
        )
        force_github = (
            os.getenv("DIRECTOR_FORCE_GITHUB", "").lower() in {"1", "true", "yes"}
            or bool(stale)
            or float(net.get("net_usd_est", 0)) <= -max_cumulative_net_loss_usd()
        )
        force_nexus = force_github or focus == "revenue" or continuous
        budget_ok = float(os.getenv("GROK_EVOLUTION_BUDGET_USD", "0.75")) > 0
        revenue_friction = (
            focus == "revenue"
            and "no_verified_revenue" in analysis.get("bottlenecks", [])
        )
        unmatched = int(execution.get("treasury_unmatched_inflows", 0) or 0) > 0
        allow_grok = (
            gates.get("all_passed")
            and budget_ok
            and (
                focus in ("tools", "rsi")
                or revenue_friction
                or unmatched
            )
        )

        plan = CyclePlan(
            cycle_id_next=cycle_id + 1,
            mode=next_mode,
            focus=focus,
            sleep_minutes=sleep_min,
            stop_reason=stop_reason,
            throttle_from=throttle_from,
            force_github_distribution=force_github,
            force_nexus_emit=force_nexus,
            evolution_priorities=evolution_priorities,
            allow_grok_evolution=allow_grok,
            reasoning=reasoning,
        )

        _append_decision({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "after_cycle_id": cycle_id,
            **asdict(plan),
        })
        return plan

    def _should_prioritize_revenue(
        self,
        net: Dict[str, Any],
        gates: Dict[str, Any],
        analysis: Dict[str, Any],
    ) -> bool:
        """Director override: organic gap large + gates healthy → revenue sprint."""
        organic_gap = max(
            0.0,
            REVENUE_TARGET_USD - float(net.get("organic_revenue_usd_est", 0)),
        )
        if organic_gap < REVENUE_TARGET_USD * 0.5:
            return False
        if not gates.get("all_passed"):
            return False
        if "no_verified_revenue" not in analysis.get("bottlenecks", []):
            return False
        return True

    def _evolution_priorities(
        self,
        focus: str,
        stale: List[str],
        execution: Dict[str, Any],
        gates_passed: bool,
        factory_state: Optional[FactoryState] = None,
    ) -> List[str]:
        """Ordered evolution actions for Phase 6 (deterministic keys)."""
        if not gates_passed:
            return []

        priorities: List[str] = []
        stale_normalized = [s.lower() for s in stale]

        for title in stale:
            lower = title.lower()
            if "accelerate treasury" in lower:
                priorities.append("accelerate_treasury_surfaces")
            elif "refresh live tip" in lower:
                priorities.append("refresh_tip_surfaces")
            elif "treasury ingest" in lower:
                priorities.append("treasury_ingest_github")
            elif "payment_intent" in lower:
                priorities.append("harden_payment_intent")
            elif "tool_improvements.jsonl" in lower:
                priorities.append("tool_analytics")
            elif "batch vercel" in lower:
                priorities.append("batch_vercel_deploy")

        if execution.get("treasury_unmatched_inflows", 0) > 0:
            priorities.append("grok_payment_friction")

        if focus == "revenue":
            if not is_proposal_implemented("Treasury ingest + GitHub issue refresh", factory_state):
                if "treasury_ingest_github" not in priorities:
                    priorities.append("treasury_ingest_github")
            elif "accelerate_treasury_surfaces" not in priorities:
                priorities.append("accelerate_treasury_surfaces")

        if focus == "tools" and "harden_payment_intent" not in priorities:
            if not is_proposal_implemented("Harden payment_intent ingest paths", factory_state):
                priorities.append("harden_payment_intent")

        if focus == "rsi" and not priorities:
            priorities.append("grok_rsi_meta")

        _ = stale_normalized  # reserved for future fuzzy matching

        seen: set[str] = set()
        ordered: List[str] = []
        for item in priorities:
            if item not in seen:
                seen.add(item)
                ordered.append(item)
        return ordered[:3]

    def configure_autonomous_env(self, plan: CyclePlan) -> None:
        """Apply director mode plan to runner environment."""
        plan.apply_env()
        if plan.mode == "tool_improvement":
            os.environ["VERCEL_DEPLOY"] = "false"
            os.environ["REVENUE_ENGINES"] = ""
        elif plan.mode == "hybrid":
            os.environ["VERCEL_DEPLOY"] = "true"
            os.environ.setdefault(
                "REVENUE_ENGINES", "content_operator,tipping_funnel,paid_briefing"
            )
            os.environ["REVENUE_PURSUIT"] = "true"
            if plan.focus == "revenue" or os.getenv("FACTORY_REQUIRE_LIVE_URL", "true").lower() in {
                "1",
                "true",
                "yes",
            }:
                os.environ["REQUIRE_LIVE_URL"] = "true"
        else:
            os.environ["VERCEL_DEPLOY"] = "true"
            os.environ.setdefault(
                "REVENUE_ENGINES", "content_operator,tipping_funnel,paid_briefing"
            )


# Module singleton for runners
director = FactoryDirector()