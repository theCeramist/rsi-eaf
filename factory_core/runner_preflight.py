"""
Autonomous runner preflight — validate environment before (re)starting cycles.
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Any, Dict, List

from factory_core.revenue_fitness import evaluate_revenue_models
from observability.economic_ledger import ledger
from tools.github_ci_gate import latest_workflow_run


def run_preflight() -> Dict[str, Any]:
    """Checks factory readiness; returns blockers and warnings."""
    blockers: List[str] = []
    warnings: List[str] = []
    checks: Dict[str, Any] = {}

    if not (os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")):
        warnings.append("no_github_token — distribution/nexus may skip")

    rsi_ci = latest_workflow_run("theCeramist", "rsi-eaf")
    checks["rsi_eaf_ci"] = rsi_ci
    if rsi_ci.get("conclusion") == "failure":
        warnings.append(f"rsi-eaf CI red: {rsi_ci.get('html_url')}")

    nexus_owner = os.getenv("NEXUS_CI_GATE_OWNER", os.getenv("NEXUS_GITHUB_OWNER", "theCeramist"))
    nexus_repo = os.getenv("NEXUS_CI_GATE_REPO", os.getenv("NEXUS_GITHUB_REPO", "jarvis-swarm"))
    nexus_ci = latest_workflow_run(nexus_owner, nexus_repo)
    checks["nexus_ci"] = nexus_ci
    if nexus_ci.get("conclusion") == "failure":
        warnings.append(f"nexus CI red ({nexus_repo}): {nexus_ci.get('html_url')}")

    net = ledger.calculate_net()
    checks["ledger_net"] = net
    if float(net.get("organic_revenue_usd_est", 0)) <= 0:
        warnings.append("organic_revenue_zero — revenue sprint expected")

    fitness = evaluate_revenue_models()
    checks["revenue_fitness"] = fitness

    if os.getenv("FACTORY_PREFLIGHT_PYTEST", "true").lower() in {"1", "true", "yes"}:
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", "tests/test_core.py", "-q", "--tb=no"],
                capture_output=True,
                text=True,
                timeout=120,
                cwd=os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
            )
            checks["pytest"] = {"exit_code": proc.returncode, "tail": (proc.stdout or "")[-400:]}
            if proc.returncode != 0:
                blockers.append("pytest test_core.py failed — fix before restart")
        except (subprocess.TimeoutExpired, OSError) as exc:
            warnings.append(f"pytest preflight skipped: {exc}")

    ok = len(blockers) == 0
    return {
        "ok": ok,
        "blockers": blockers,
        "warnings": warnings,
        "checks": checks,
        "top3_revenue": fitness.get("top3_ids"),
    }