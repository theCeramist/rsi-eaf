"""
Improvement proposals — Grok Build Plan Mode with rule-based fallback.
"""

import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

PROPOSALS_DIR = Path(os.getenv("FACTORY_PROPOSALS_DIR", "factory_core/proposals"))
GROK_BIN = os.getenv("GROK_BIN", shutil.which("grok") or os.path.expanduser("~/.grok/bin/grok.exe"))
PROPOSAL_TIMEOUT = int(os.getenv("GROK_PROPOSAL_TIMEOUT_SEC", "120"))


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


def propose_improvements(analysis: Dict[str, Any], cycle_id: int) -> List[Dict[str, Any]]:
    """Generate proposals via grok build -p or fallback rules."""
    PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)
    prompt = (
        f"RSI-EAF cycle {cycle_id} analysis:\n{json.dumps(analysis, indent=2)}\n\n"
        "Propose exactly ONE surgical improvement per AGENTS.md with expected economic delta, "
        "verification strategy (including XRPL steps), and risk assessment. JSON array only."
    )

    if GROK_BIN and Path(GROK_BIN).exists():
        try:
            result = subprocess.run(
                [GROK_BIN, "build", "-p", prompt],
                capture_output=True,
                text=True,
                timeout=PROPOSAL_TIMEOUT,
                cwd=os.getcwd(),
                check=False,
            )
            output = (result.stdout or "") + (result.stderr or "")
            artifact = {
                "cycle_id": cycle_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source": "grok_build_plan",
                "exit_code": result.returncode,
                "output_tail": output[-2000:],
            }
            out_path = PROPOSALS_DIR / f"cycle-{cycle_id}-grok.json"
            out_path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
            if result.returncode == 0:
                return [{
                    "title": "Grok Plan Mode proposal",
                    "impact": "See factory_core/proposals artifact",
                    "verification": "Independent gate run + XRPL confirmation",
                    "source": "grok_build_plan",
                    "artifact": str(out_path),
                }]
        except (subprocess.TimeoutExpired, OSError) as exc:
            print(f"[Proposer] Grok subprocess failed: {exc}")

    proposals = _rule_based_proposals(analysis)
    out_path = PROPOSALS_DIR / f"cycle-{cycle_id}-rules.json"
    out_path.write_text(json.dumps(proposals, indent=2), encoding="utf-8")
    return proposals