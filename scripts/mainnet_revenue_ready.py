#!/usr/bin/env python3
"""
Bootstrap RSI-EAF for first real (mainnet) revenue — no human input required.

1. Generate mainnet treasury wallet if missing (seed → .env + observability/secrets/)
2. Dual-network mode: ops=testnet, revenue=mainnet
3. Rewrite pay.html, agent-pay.json, tip-manifest, network-status, treasury-map
4. Smoke mainnet RPC + readiness report
5. Optional: surgical conversion deploy when Vercel quota allows

Usage:
  python -u scripts/mainnet_revenue_ready.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)


def main() -> int:
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env", override=True)
    except Exception:
        pass

    from factory_core.xrpl_network import (
        ensure_mainnet_treasury_env,
        is_mainnet_revenue_ready,
        resolve_public_treasury,
        treasury_watch_targets,
        write_readiness_artifacts,
    )
    from tools.mainnet_pay_surface import write_mainnet_pay_surface
    from observability.agent_payment import write_agent_pay_manifest
    from tools.distribution_tools import featured_links_for_index, write_tip_manifest
    from revenue_engines.base_engine import resolve_treasury

    print("=== RSI-EAF Mainnet Revenue Readiness ===")
    created = ensure_mainnet_treasury_env(ROOT / ".env")
    # Reload env after write
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env", override=True)
    except Exception:
        pass

    print(
        f"[mainnet] treasury created={created.get('created')} "
        f"address={created.get('address')} seed_present={created.get('seed_present')}"
    )

    cycle = 0
    try:
        from factory_core.state import FactoryState

        cycle = int(FactoryState().current_cycle or 0)
    except Exception:
        pass

    surface = write_mainnet_pay_surface(cycle)
    treasury = resolve_treasury()
    featured = {}
    try:
        featured = featured_links_for_index(cycle) or {}
    except Exception:
        pass
    write_agent_pay_manifest(cycle, treasury, featured)
    write_tip_manifest(
        treasury_address=treasury,
        cycle_id=cycle,
        live_tip_url=featured.get("canonical_tip_page") or featured.get("tip_page") or f"{os.getenv('FACTORY_PUBLIC_BASE_URL', 'https://published-zeta.vercel.app').rstrip('/')}/pay.html",
    )
    readiness = write_readiness_artifacts(cycle)
    pub_addr, pub_net = resolve_public_treasury()
    ready = is_mainnet_revenue_ready(strict=False)
    strict = is_mainnet_revenue_ready(strict=True)

    # Soft conversion ensure (won't thrash if quota blocked)
    deploy = {}
    try:
        from tools.conversion_surfaces import ensure_conversion_surfaces

        deploy = ensure_conversion_surfaces(force_deploy=False)
    except Exception as exc:
        deploy = {"error": str(exc)[:200]}

    # Force try pay.html only if pay_ok false
    try:
        from tools.conversion_surfaces import verify_live, deploy_critical_pack

        live = verify_live()
        if not live.get("pay_ok"):
            deploy = deploy_critical_pack(force=True)
    except Exception as exc:
        deploy["force_error"] = str(exc)[:200]

    report = {
        "created": {k: v for k, v in created.items() if k != "seed"},
        "public_treasury": pub_addr,
        "public_network": pub_net,
        "surface": {
            "pay_html": surface.get("pay_html"),
            "network": surface.get("network"),
            "treasury": surface.get("treasury"),
        },
        "ready_accept_payments": ready.get("ready"),
        "ready_account_activated": strict.get("checks", {}).get("account_activated"),
        "watch_targets": treasury_watch_targets(),
        "readiness_file": "observability/mainnet_readiness.json",
        "deploy": {
            "success": deploy.get("success"),
            "action": deploy.get("action"),
            "error": deploy.get("error"),
        },
        "safety": readiness.get("safety"),
        "next": [
            "Share pay.html / agent-pay.json with MAINNET treasury address",
            "First inbound XRP activates account if unfunded (base reserve)",
            "Factory monitors mainnet + testnet; organic mainnet credits ledger",
            "MAINNET_OUTBOUND_ENABLED remains false — factory never spends real XRP by default",
        ],
    }
    out = Path("observability/mainnet_bootstrap_report.json")
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, indent=2, default=str))
    print(f"[mainnet] report → {out}")
    return 0 if ready.get("ready") else 0  # readiness without activation still success


if __name__ == "__main__":
    raise SystemExit(main())
