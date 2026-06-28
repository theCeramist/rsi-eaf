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


def _maybe_run_revenue_smoke_test() -> Dict[str, Any]:
    """Optional E2E treasury ingest proof when supporter wallet is configured."""
    enabled = os.getenv("REVENUE_INGEST_SMOKE_TEST", "false").lower() in {"1", "true", "yes"}
    if not enabled:
        return {"skipped": True, "reason": "REVENUE_INGEST_SMOKE_TEST disabled"}

    supporter_seed = os.getenv("TEST_SUPPORTER_SEED", "").strip()
    if not supporter_seed:
        return {"skipped": True, "reason": "TEST_SUPPORTER_SEED not set"}

    from gates.verifier import count_verified_revenue_events

    if count_verified_revenue_events() > 0:
        return {"skipped": True, "reason": "verified_revenue_already_present"}

    try:
        from xrpl.wallet import Wallet

        from tools.xrpl_tools import get_revenue_destination, load_factory_wallet, send_xrp_payment

        factory = load_factory_wallet(testnet=True)
        treasury = os.getenv("FACTORY_TREASURY_ADDRESS") or get_revenue_destination(factory)
        if treasury == factory.classic_address:
            return {"skipped": True, "reason": "treasury_same_as_factory"}

        supporter = Wallet.from_seed(supporter_seed)
        amount_usd = float(os.getenv("REVENUE_SMOKE_AMOUNT_USD", "1.0"))
        amount_xrp = float(os.getenv("REVENUE_SMOKE_AMOUNT_XRP", "0.01"))
        memo = {
            "type": "revenue",
            "amount_usd_est": amount_usd,
            "notes": "preflight revenue ingest smoke test",
            "source": "preflight_smoke_test",
        }
        result = send_xrp_payment(
            wallet=supporter,
            destination=treasury,
            amount_xrp=amount_xrp,
            memo_data=memo,
            destination_tag=1,
            verbose=False,
        )
        return {
            "executed": bool(result.get("success")),
            "tx_hash": result.get("tx_hash"),
            "explorer_url": result.get("explorer_url"),
            "amount_usd_est": amount_usd,
        }
    except Exception as exc:
        return {"executed": False, "error": str(exc)}


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

    smoke = _maybe_run_revenue_smoke_test()
    checks["revenue_smoke_test"] = smoke
    if smoke.get("executed"):
        warnings.append(f"revenue_smoke_test_sent tx={smoke.get('tx_hash')}")
    elif smoke.get("error"):
        warnings.append(f"revenue_smoke_test_failed: {smoke['error']}")

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