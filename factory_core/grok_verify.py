"""
Grok verifier — independent read-only pass after evolution changes.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

from factory_core.grok_cli import run_headless


def verify_evolution_change(
    cycle_id: int,
    evolution_result: Dict[str, Any],
    gate_result: Dict[str, Any],
) -> Dict[str, Any]:
    """Run explore-only Grok pass to validate evolution against gates."""
    if os.getenv("GROK_VERIFY_EVOLUTION", "true").lower() not in {"1", "true", "yes"}:
        return {"skipped": True, "reason": "GROK_VERIFY_EVOLUTION disabled"}

    prompt = (
        f"RSI-EAF cycle {cycle_id} evolution verification.\n"
        f"Evolution: {json.dumps(evolution_result, default=str)[:4000]}\n"
        f"Gates: {json.dumps(gate_result, default=str)[:2000]}\n\n"
        "Read-only review: did evolution respect AGENTS.md surgical merge? "
        "Return JSON: {{\"approved\": bool, \"issues\": [], \"xrpl_checks\": []}}"
    )
    return run_headless(prompt, mode="verify", max_turns=4, cycle_id=cycle_id)