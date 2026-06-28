"""
Headless micro-SaaS scout — periodic niche opportunity ranking for micro_saas_factory.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

SCOUT_FILE = Path(os.getenv("MICRO_SAAS_SCOUT_FILE", "observability/micro_saas_scout.json"))
SCOUT_LOG = Path(os.getenv("MICRO_SAAS_SCOUT_LOG", "observability/micro_saas_scout.jsonl"))


def should_run_scout(cycle_id: int) -> bool:
    if os.getenv("MICRO_SAAS_SCOUT_ENABLED", "true").lower() not in {"1", "true", "yes"}:
        return False
    every = int(os.getenv("MICRO_SAAS_SCOUT_EVERY_N_CYCLES", "5"))
    return cycle_id % every == 0


def run_micro_saas_scout(cycle_id: int, intel: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from factory_core.grok_cli import run_plan_prompt
    from observability.economic_ledger import ledger

    net = ledger.calculate_net()
    prompt = (
        f"RSI-EAF cycle {cycle_id} micro-SaaS scout.\n"
        f"Ledger: {json.dumps(net, default=str)[:2000]}\n"
        f"Intel: {json.dumps(intel or {}, default=str)[:2000]}\n\n"
        "Plan-only. Rank 3 niche micro-tool opportunities agents would pay for via XRPL tags.\n"
        "Return JSON: {\"opportunities\":[{\"niche\":\"\",\"title\":\"\",\"price_usd\":3,"
        "\"xrpl_tag\":3,\"fitness\":0.0,\"rationale\":\"\"}]}"
    )
    result = run_plan_prompt(prompt, cycle_id=cycle_id)
    parsed = result.get("parsed") or {}
    opportunities: List[Dict[str, Any]] = parsed.get("opportunities") or []

    payload = {
        "schema": "rsi_eaf_micro_saas_scout_v1",
        "cycle_id": cycle_id,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "opportunities": opportunities[:5],
        "grok_session": result.get("session_id"),
    }
    SCOUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    SCOUT_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    with SCOUT_LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, default=str) + "\n")

    return {"lane": "micro_saas_scout", "opportunities_count": len(opportunities), "scout": payload, "grok": result}


def top_scout_opportunity() -> Optional[Dict[str, Any]]:
    if not SCOUT_FILE.exists():
        return None
    try:
        data = json.loads(SCOUT_FILE.read_text(encoding="utf-8"))
        opps = data.get("opportunities") or []
        if not opps:
            return None
        return max(opps, key=lambda o: float(o.get("fitness", 0)))
    except (json.JSONDecodeError, OSError):
        return None