"""
Tool improvement loop — pytest, XRPL health, surgical tool evolution (no revenue engines).
"""

import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from observability.economic_ledger import ledger
from tools.xrpl_tools import get_client, get_account_xrp_balance, load_factory_wallet

IMPROVEMENTS_LOG = Path(os.getenv("TOOL_IMPROVEMENTS_LOG", "factory_core/tool_improvements.jsonl"))
TEST_PATH = os.getenv("TOOL_IMPROVEMENT_TEST_PATH", "tests/test_core.py")


def _append_log(entry: Dict[str, Any]) -> None:
    IMPROVEMENTS_LOG.parent.mkdir(parents=True, exist_ok=True)
    with IMPROVEMENTS_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")


def _isolated_pytest_env() -> Dict[str, str]:
    """Pytest must not inherit runner overrides (loss ceiling, continuous mode)."""
    try:
        from factory_core.pytest_isolation import isolated_pytest_env

        return isolated_pytest_env()
    except ImportError:
        env = os.environ.copy()
        for key in (
            "MAX_CUMULATIVE_NET_LOSS_USD",
            "FACTORY_RUN_CONTINUOUS",
            "CYCLE_MODE",
            "CYCLE_FOCUS",
            "SKIP_VERCEL_DEPLOY",
            "FACTORY_RUNNER_ACTIVE",
        ):
            env.pop(key, None)
        return env


def run_pytest() -> Dict[str, Any]:
    start = time.time()
    try:
        from factory_core.pytest_isolation import (
            isolated_pytest_env,
            pytest_timeout_sec,
            tool_gate_pytest_argv,
        )

        argv = tool_gate_pytest_argv()
        env = isolated_pytest_env()
        timeout = pytest_timeout_sec()
        cwd = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    except ImportError:
        import sys

        markers = os.getenv("TOOL_IMPROVEMENT_TEST_MARKERS", "not meta")
        argv = [sys.executable, "-m", "pytest", TEST_PATH, "-q", "--tb=no"]
        if markers.strip():
            argv.extend(["-m", markers.strip()])
        env = os.environ.copy()
        for key in (
            "MAX_CUMULATIVE_NET_LOSS_USD",
            "FACTORY_RUN_CONTINUOUS",
            "CYCLE_MODE",
            "FACTORY_RUNNER_ACTIVE",
        ):
            env.pop(key, None)
        timeout = int(os.getenv("FACTORY_PYTEST_TIMEOUT_SEC", "600"))
        cwd = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    result = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        cwd=cwd,
        check=False,
        env=env,
        timeout=timeout,
    )
    output = (result.stdout or "") + (result.stderr or "")
    passed = result.returncode == 0
    return {
        "passed": passed,
        "exit_code": result.returncode,
        "duration_ms": round((time.time() - start) * 1000, 1),
        "output_tail": output[-800:],
    }


def check_xrpl_connectivity() -> Dict[str, Any]:
    try:
        wallet = load_factory_wallet(testnet=True)
        client = get_client(testnet=True)
        from xrpl.models.requests import ServerInfo

        info = client.request(ServerInfo())
        balance = float(get_account_xrp_balance(wallet.classic_address))
        return {
            "ok": True,
            "factory_address": wallet.classic_address,
            "balance_xrp": balance,
            "ledger_index": info.result.get("info", {}).get("validated_ledger", {}).get("seq"),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def analyze_tool_bottlenecks() -> List[Dict[str, Any]]:
    """Rule-based tool improvement opportunities from factory state."""
    opportunities = []
    from tools.publish_tools import deploy_cooldown_status

    cooldown = deploy_cooldown_status()
    if cooldown.get("active"):
        opportunities.append({
            "tool": "publish_tools",
            "issue": "vercel_deploy_cooldown",
            "detail": cooldown.get("reason"),
            "action": "skip_deploy_this_cycle",
        })
    opportunities.append({
        "tool": "revenue_engines/registry",
        "issue": "per_engine_vercel_deploy",
        "action": "batch_deploy_once_per_cycle",
        "status": "implemented",
    })
    opportunities.append({
        "tool": "observability/payment_intent",
        "issue": "human_payment_friction",
        "action": "destination_tag_primary_path",
        "status": "implemented",
    })
    try:
        from tools.publish_tools import quota_exhausted_status

        quota = quota_exhausted_status()
        if quota.get("exhausted"):
            opportunities.append({
                "tool": "publish_tools",
                "issue": "vercel_deploy_quota_exhausted",
                "action": "use_api_deploy_fallback",
                "detail": quota.get("reason"),
                "status": "workaround_active",
            })
    except Exception:
        pass
    return opportunities


def run_tool_improvement_cycle(cycle_id: int) -> Dict[str, Any]:
    """Execute tool-improvement phase instead of revenue engines."""
    print("[ToolImprover] Running tool improvement cycle...")
    t0 = time.time()

    from factory_core.pytest_cache import (
        get_reusable_pytest_result,
        set_pytest_result,
        tool_gate_pytest_every_n,
    )

    reused = get_reusable_pytest_result(cycle_id)
    if reused:
        print(
            f"[ToolImprover] Reusing pytest pass from cycle "
            f"{reused.get('reused_from_cycle')} "
            f"(every {tool_gate_pytest_every_n()} cycles in continuous mode)"
        )
        # Memory-only: do not rewrite disk watermark or age resets and pytest never re-runs.
        from factory_core import pytest_cache as _pc

        _pc._cache[cycle_id] = {
            "passed": True,
            "exit_code": reused.get("exit_code", 0),
            "duration_ms": 0,
            "output_tail": (reused.get("output_tail") or "")[-200:],
            "reused": True,
            "reused_from_cycle": reused.get("reused_from_cycle"),
        }
        pytest_result = _pc._cache[cycle_id]
    else:
        pytest_result = run_pytest()
        set_pytest_result(cycle_id, pytest_result)
    xrpl_result = check_xrpl_connectivity()
    opportunities = analyze_tool_bottlenecks()

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "cycle_id": cycle_id,
        "pytest": pytest_result,
        "xrpl": xrpl_result,
        "opportunities": opportunities,
        "duration_ms": round((time.time() - t0) * 1000, 1),
    }
    _append_log(entry)

    ledger.log_event(
        event_type="milestone",
        source="tool_improver",
        amount_usd_est=0.0,
        cycle_id=cycle_id,
        metadata={"phase": "tool_improvement", **entry},
        anchor_to_xrpl=False,
    )

    success = pytest_result["passed"] and xrpl_result.get("ok", False)
    return {
        "mode": "tool_improvement",
        "success": success,
        "pytest_passed": pytest_result["passed"],
        "xrpl_ok": xrpl_result.get("ok", False),
        "tool_improvements_log": str(IMPROVEMENTS_LOG),
        "opportunities": opportunities,
        "pytest": pytest_result,
        "xrpl": xrpl_result,
        "published_asset": str(IMPROVEMENTS_LOG),
        "published_assets": [str(IMPROVEMENTS_LOG)],
        "live_url": None,
        "live_verified": False,
        "xrpl_tx_hash": None,
        "xrpl_payments_made": 0,
        "revenue_engines_run": [],
    }


def evolve_tools(cycle_id: int, proposals: List[Dict[str, Any]], gate_result: Dict[str, Any]) -> Dict[str, Any]:
    """Record tool evolution intent; surgical patches applied in-repo by agent cycles."""
    from gates.verifier import gates_evolution_allowed

    if not gates_evolution_allowed(gate_result):
        return {"evolved": False, "reason": "tool_gates_failed"}

    focus = [p for p in proposals if p.get("source") == "tool_improvement"]
    _append_log({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "cycle_id": cycle_id,
        "phase": "evolve_tools",
        "proposals_applied": len(focus),
        "proposals": focus,
    })
    return {
        "evolved": True,
        "tool_proposals": focus,
        "note": "Tool improvements logged; deploy cooldown and batch publish active.",
    }