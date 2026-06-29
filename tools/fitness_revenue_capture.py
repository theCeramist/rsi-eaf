"""
Fitness evolution action — maximize probability of verified treasury revenue.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from observability.revenue_ingest import ingest_verified_xrpl_revenue, reconcile_unmatched_treasury_payments


def run_fitness_revenue_capture(
    cycle_id: int,
    treasury_address: str,
    featured: Optional[Dict[str, str]] = None,
    factory_state: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    One-shot fitness evolution: agent-pay surface + ingest sweep + optional smoke.
    """
    from observability.agent_payment import write_agent_pay_manifest
    from tools.distribution_tools import featured_links_for_index, write_tip_manifest
    from tools.publish_tools import build_index_html, deploy_to_vercel, verify_live_url
    from tools.revenue_acceleration import write_outreach_bundle

    featured = featured or featured_links_for_index(cycle_id)
    agent_pay_path = write_agent_pay_manifest(cycle_id, treasury_address, featured)
    write_tip_manifest(
        treasury_address=treasury_address,
        cycle_id=cycle_id,
        live_tip_url=featured.get("tip_page"),
    )
    build_index_html(treasury_address=treasury_address, featured=featured)
    outreach = write_outreach_bundle(cycle_id, treasury_address, featured)
    outreach["payload"]["agent_pay_url"] = featured.get("agent_pay")

    reconciled = reconcile_unmatched_treasury_payments(cycle_id)
    ingest = ingest_verified_xrpl_revenue(
        cycle_id=cycle_id,
        treasury_address=treasury_address,
        factory_state=factory_state,
    )
    ingested = list(ingest.get("ingested") or []) + list(reconciled or [])

    smoke: Dict[str, Any] = {"skipped": True}
    if os.getenv("FITNESS_EVOLUTION_SMOKE", "true").lower() in {"1", "true", "yes"}:
        try:
            from factory_core.runner_preflight import _maybe_run_revenue_smoke_test

            smoke = _maybe_run_revenue_smoke_test()
        except Exception as exc:
            smoke = {"error": str(exc)}

    deploy = deploy_to_vercel()
    agent_pay_url = featured.get("agent_pay")
    agent_pay_live = verify_live_url(agent_pay_url) if agent_pay_url else False

    implemented = bool(ingested) or smoke.get("executed") or agent_pay_live or deploy.get("success")

    if factory_state is not None and implemented:
        factory_state.mark_proposal_implemented("Fix verified_revenue_pipeline")

    return {
        "action": "fitness_revenue_capture",
        "implemented": implemented,
        "agent_pay_path": str(agent_pay_path),
        "agent_pay_live": agent_pay_live,
        "ingested_count": len(ingested),
        "reconciled_count": len(reconciled),
        "ingest": ingest,
        "smoke_test": smoke,
        "deploy": deploy,
        "outreach": outreach,
        "cycle_id": cycle_id,
        "fitness_note": "Evolution keyed to primary goal — verified treasury revenue",
    }