#!/usr/bin/env python3
"""
Factory FLY mode — max economic + distribution thrust without X spam suicide.

Runs: mainnet pay surfaces, force deploy, link watcher, revenue ingest/sprint,
autonomous outreach, manifests, scoreboard, plugin stack, guardian, X tick
(under probation rules — never force broadcast).

Usage:
  python -u scripts/factory_fly.py
  python -u scripts/factory_fly.py --skip-x
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> int:
    os.chdir(ROOT)
    try:
        from dotenv import load_dotenv

        load_dotenv(override=True)
    except Exception:
        pass

    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-x", action="store_true")
    ap.add_argument("--skip-deploy", action="store_true")
    args = ap.parse_args()

    os.environ.setdefault("REMEDIATE_CLEAR_QUOTA", "true")
    out: Dict[str, Any] = {"at": _now(), "mode": "fly", "steps": []}

    def step(name: str, fn: Callable[[], Any]) -> None:
        try:
            r = fn()
            rec: Dict[str, Any] = {"step": name, "ok": True}
            if isinstance(r, dict):
                rec["ok"] = bool(r.get("success", r.get("all_ok", r.get("ok", True))))
            out["steps"].append(rec)
            print(name, "OK" if rec["ok"] else "PARTIAL", flush=True)
        except Exception as exc:
            out["steps"].append({"step": name, "ok": False, "error": str(exc)[:300]})
            print(name, "FAIL", exc, flush=True)

    from factory_core.state import FactoryState

    cid = int(FactoryState().current_cycle or 0)
    print("cycle", cid, flush=True)

    from tools.mainnet_pay_surface import write_mainnet_pay_surface
    from tools.factory_remediate import (
        force_deploy_critical,
        regenerate_all_local_surfaces,
        remediate_business_red,
        verify_must_live,
    )

    step("mainnet_pay", lambda: write_mainnet_pay_surface(cid))
    step("regenerate", lambda: regenerate_all_local_surfaces(cid))
    if not args.skip_deploy:
        step("force_deploy", force_deploy_critical)
    step("verify_live", verify_must_live)

    from tools.link_watcher import run_link_watcher

    step("link_watcher", lambda: run_link_watcher(remediate=True))

    from observability.revenue_ingest import ingest_verified_xrpl_revenue

    step("revenue_ingest", lambda: ingest_verified_xrpl_revenue(cid))

    try:
        from factory_core.revenue_sprint import run_revenue_sprint
        from observability.economic_ledger import ledger

        analysis = {"net_cumulative": ledger.calculate_net()}
        step("revenue_sprint", lambda: run_revenue_sprint(cid, analysis, None) or {"success": True})
    except Exception as exc:
        out["steps"].append({"step": "revenue_sprint", "ok": False, "error": str(exc)[:200]})

    step("business_red_machinery", lambda: remediate_business_red(cycle_id=cid, skip_deploy_if_green=True))

    try:
        from tools.autonomous_outreach import run_autonomous_outreach

        step("autonomous_outreach", lambda: run_autonomous_outreach(cid, force=True))
    except Exception as exc:
        out["steps"].append({"step": "autonomous_outreach", "ok": False, "error": str(exc)[:200]})

    from observability.agent_payment import write_agent_pay_manifest
    from revenue_engines.base_engine import resolve_treasury
    from tools.distribution_tools import featured_links_for_index, write_tip_manifest

    def _manifests() -> Dict[str, Any]:
        t = resolve_treasury()
        f = featured_links_for_index(cid) or {}
        write_agent_pay_manifest(cid, t, f)
        write_tip_manifest(
            treasury_address=t,
            cycle_id=cid,
            live_tip_url=f.get("canonical_tip_page") or "https://published-zeta.vercel.app/pay.html",
        )
        return {"success": True, "treasury": t}

    step("manifests", _manifests)

    from tools.factory_scoreboard import write_scoreboard

    step("scoreboard", lambda: write_scoreboard() or {"success": True})

    try:
        from factory_core.social_policy import write_policy_artifacts

        step("social_policy", lambda: write_policy_artifacts() or {"success": True})
    except Exception as exc:
        out["steps"].append({"step": "social_policy", "ok": False, "error": str(exc)[:200]})

    try:
        from tools.plugin_stack import run_plugin_stack

        step("plugin_stack", lambda: run_plugin_stack(cid, force=True))
    except Exception as exc:
        out["steps"].append({"step": "plugin_stack", "ok": False, "error": str(exc)[:200]})

    try:
        from factory_core.blocker_guardian import run_guardian_pass

        st_path = Path("runtime/factory_cli_supervisor_state.json")
        st = json.loads(st_path.read_text(encoding="utf-8")) if st_path.exists() else {}
        step(
            "guardian",
            lambda: run_guardian_pass(
                hybrid_pid=(st.get("hybrid") or {}).get("pid"),
                x_daemon_pid=(st.get("x_daemon") or {}).get("pid"),
                hybrid_uptime_min=5.0,
            ),
        )
    except Exception as exc:
        out["steps"].append({"step": "guardian", "ok": False, "error": str(exc)[:200]})

    if not args.skip_x:
        try:
            from tools.x_agent import run_x_agent_tick

            # Never force broadcast — probation / rules first
            step("x_tick", lambda: run_x_agent_tick(force_broadcast=False))
        except Exception as exc:
            out["steps"].append({"step": "x_tick", "ok": False, "error": str(exc)[:200]})

    pub = Path("public_pay")
    pub.mkdir(exist_ok=True)
    for n in (
        "pay.html",
        "agent-pay.json",
        "tip-manifest.json",
        "network-status.json",
        "treasury-map.json",
        "icp.json",
    ):
        s = Path("published") / n
        if s.exists():
            shutil.copy(s, pub / n)
    out["steps"].append({"step": "cdn_sync", "ok": True})

    out["ok_steps"] = sum(1 for s in out["steps"] if s.get("ok"))
    out["n_steps"] = len(out["steps"])
    Path("observability").mkdir(exist_ok=True)
    Path("observability/factory_fly_latest.json").write_text(
        json.dumps(out, indent=2, default=str), encoding="utf-8"
    )
    print(json.dumps({"ok_steps": out["ok_steps"], "n": out["n_steps"]}, indent=2), flush=True)
    return 0 if out["ok_steps"] >= max(1, out["n_steps"] // 2) else 1


if __name__ == "__main__":
    raise SystemExit(main())
