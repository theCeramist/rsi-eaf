"""
Headless revenue sprint — parallel analyze lane when organic revenue is zero.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

SPRINT_LOG = Path(os.getenv("REVENUE_SPRINT_LOG", "observability/revenue_sprint.jsonl"))


def should_run_revenue_sprint(
    organic_revenue: float,
    consecutive_zero: int = 0,
) -> bool:
    if os.getenv("REVENUE_SPRINT_ENABLED", "true").lower() not in {"1", "true", "yes"}:
        return False
    min_zero = int(os.getenv("REVENUE_SPRINT_ZERO_CYCLES", "1"))
    return organic_revenue <= 0 and consecutive_zero >= min_zero


def run_revenue_sprint(
    cycle_id: int,
    analysis: Dict[str, Any],
    featured: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Spawn headless analyze subagents for outreach + conversion hypotheses."""
    from factory_core.grok_cli import run_headless
    from observability.economic_ledger import ledger

    net = ledger.calculate_net()
    intel: Dict[str, Any] = {}
    try:
        from observability.xrpl_intel_daemon import latest_intel

        intel = latest_intel()
    except Exception:
        pass

    prompt = (
        f"RSI-EAF cycle {cycle_id} REVENUE SPRINT (organic=${net.get('organic_revenue_usd_est', 0)}).\n"
        f"Analysis: {json.dumps(analysis, default=str)[:4000]}\n"
        f"Featured surfaces: {json.dumps(featured or {}, default=str)[:2000]}\n"
        f"XRPL intel: {json.dumps(intel, default=str)[:1500]}\n\n"
        "Read-only analysis. Return JSON:\n"
        '{"outreach_targets":[],"share_text_variants":[],"tag_messaging":{},'
        '"agent_payment_ux":[],"expected_conversion_delta_usd":0}'
    )
    agents = [
        {
            "name": "outreach_strategist",
            "type": "explore",
            "prompt": "Where should RSI-EAF post tip links for XRPL testnet revenue?",
        },
        {
            "name": "agent_commerce_analyst",
            "type": "explore",
            "prompt": "How should destination tags 1-5 be messaged for agent buyers?",
        },
    ]
    result = run_headless(prompt, mode="analyze", agents=agents, max_turns=8, cycle_id=cycle_id)

    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "cycle_id": cycle_id,
        "organic_revenue": net.get("organic_revenue_usd_est"),
        "executed": result.get("executed"),
        "session_id": result.get("session_id"),
        "parsed": result.get("parsed"),
    }
    SPRINT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with SPRINT_LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, default=str) + "\n")

    _apply_sprint_outreach(cycle_id, result, featured)
    return {"lane": "revenue_sprint", **record, "grok": result}


def _apply_sprint_outreach(
    cycle_id: int,
    grok_result: Dict[str, Any],
    featured: Optional[Dict[str, str]],
) -> None:
    """Persist sprint variants alongside standard outreach when Grok returns copy."""
    parsed = grok_result.get("parsed") or {}
    variants = parsed.get("share_text_variants") or []
    if not variants:
        return
    from revenue_engines.base_engine import resolve_treasury
    from tools.revenue_acceleration import write_outreach_bundle

    outreach = write_outreach_bundle(cycle_id, resolve_treasury(), featured)
    sprint_path = Path("published") / f"revenue-sprint-cycle-{cycle_id}.json"
    sprint_path.write_text(
        json.dumps(
            {
                "schema": "rsi_eaf_revenue_sprint_v1",
                "cycle_id": cycle_id,
                "variants": variants[:5],
                "base_outreach": outreach.get("payload"),
            },
            indent=2,
        ),
        encoding="utf-8",
    )