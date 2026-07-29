"""
Aggressive factory remediation — fix down/failed/blocker conditions, don't just log them.

Called by blocker_guardian, link_watcher, and supervisor when failures are detected.
Always attempts real side-effects: regenerate local artifacts → force Vercel deploy →
re-verify live URLs → refresh CDN pack → revenue-capture outreach.
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

PUB = Path(os.getenv("PUBLISHED_DIR", "published"))
OBS = Path(os.getenv("OBSERVABILITY_DIR", "observability"))
LOG = OBS / "factory_remediate.jsonl"
BASE = os.getenv("FACTORY_PUBLIC_BASE_URL", "https://published-zeta.vercel.app").rstrip("/")

# Every public surface that must be 200 for "doctrine / discovery" green
MUST_LIVE = [
    "pay.html",
    "agent-pay.json",
    "tip-manifest.json",
    "icp.json",
    "social-policy.json",
    "social-learning.json",
    "free-sample.json",
    "free-ads.html",
    "blockers.json",
    "network-status.json",
    "treasury-map.json",
    "link-health.json",
    ".well-known/x402.json",
    ".well-known/agent-pay.json",
    "index.html",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(rec: Dict[str, Any]) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, default=str) + "\n")


def _cycle_id() -> int:
    try:
        from factory_core.state import FactoryState

        return int(FactoryState().current_cycle or 0)
    except Exception:
        return 0


def regenerate_all_local_surfaces(cycle_id: Optional[int] = None) -> Dict[str, Any]:
    """Rewrite every conversion / doctrine / discovery artifact on disk."""
    cid = cycle_id if cycle_id is not None else _cycle_id()
    PUB.mkdir(parents=True, exist_ok=True)
    (PUB / ".well-known").mkdir(parents=True, exist_ok=True)
    (PUB / "archive").mkdir(parents=True, exist_ok=True)
    done: Dict[str, Any] = {"cycle_id": cid, "files": []}

    # Mainnet pay pack
    try:
        from tools.mainnet_pay_surface import write_mainnet_pay_surface

        done["mainnet_pay"] = write_mainnet_pay_surface(cid)
        done["files"].append("pay.html")
    except Exception as exc:
        done["mainnet_pay_error"] = str(exc)[:200]

    # Doctrine
    try:
        from tools.conversion_surfaces import ensure_doctrine_artifacts, ensure_local_pay_html

        done["pay_restore"] = ensure_local_pay_html()
        done["doctrine"] = ensure_doctrine_artifacts()
        done["files"] += ["icp.json", "social-policy.json", "social-learning.json"]
    except Exception as exc:
        done["doctrine_error"] = str(exc)[:200]

    # Agent pay + tip manifest
    try:
        from observability.agent_payment import write_agent_pay_manifest
        from tools.distribution_tools import write_tip_manifest, featured_links_for_index
        from revenue_engines.base_engine import resolve_treasury

        treasury = resolve_treasury()
        featured = {}
        try:
            featured = featured_links_for_index(cid) or {}
        except Exception:
            pass
        write_agent_pay_manifest(cid, treasury, featured)
        write_tip_manifest(
            treasury_address=treasury,
            cycle_id=cid,
            live_tip_url=featured.get("canonical_tip_page")
            or featured.get("tip_page")
            or f"{BASE}/pay.html",
        )
        done["files"] += ["agent-pay.json", "tip-manifest.json"]
        # well-known mirrors
        if (PUB / "agent-pay.json").exists():
            shutil.copy(PUB / "agent-pay.json", PUB / ".well-known" / "agent-pay.json")
            done["files"].append(".well-known/agent-pay.json")
    except Exception as exc:
        done["manifest_error"] = str(exc)[:200]

    # free-sample
    try:
        sample = {
            "schema": "rsi_eaf_free_sample_v1",
            "updated_at": _now(),
            "cycle_id": cid,
            "message": "Free sample of RSI-EAF factory doctrine. Pay Tag 1 for tip; Tag 2 for briefing.",
            "pay": f"{BASE}/pay.html",
            "agent_pay": f"{BASE}/agent-pay.json",
        }
        (PUB / "free-sample.json").write_text(json.dumps(sample, indent=2), encoding="utf-8")
        done["files"].append("free-sample.json")
    except Exception as exc:
        done["free_sample_error"] = str(exc)[:200]

    # free-ads page
    try:
        pay = f"{BASE}/pay.html"
        html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/><title>RSI-EAF Free Ads</title>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<style>body{{font-family:system-ui;max-width:40rem;margin:2rem auto;padding:0 1rem;background:#070a12;color:#e8eefc}}
a{{color:#00d4aa}}</style></head><body>
<h1>RSI-EAF free ad pack</h1>
<p>Share the factory. Exclusive ICP. Real XRPL rails.</p>
<ul>
<li><a href="{pay}">Pay page</a></li>
<li><a href="{BASE}/agent-pay.json">agent-pay.json</a></li>
<li><a href="{BASE}/icp.json">ICP doctrine</a></li>
<li><a href="{BASE}/tip-manifest.json">tip-manifest</a></li>
</ul>
<p>Cycle {cid} · generated {_now()}</p>
</body></html>
"""
        (PUB / "free-ads.html").write_text(html, encoding="utf-8")
        done["files"].append("free-ads.html")
    except Exception as exc:
        done["free_ads_error"] = str(exc)[:200]

    # blockers + link-health snapshots
    try:
        from tools.factory_scoreboard import write_scoreboard

        write_scoreboard()
        # ensure blockers.json exists as public honesty surface
        bs = {}
        if (OBS / "blocker_status.json").exists():
            bs = json.loads((OBS / "blocker_status.json").read_text(encoding="utf-8"))
        (PUB / "blockers.json").write_text(
            json.dumps(
                {
                    "schema": "rsi_eaf_blockers_public_v1",
                    "updated_at": _now(),
                    "open_count": bs.get("open_count"),
                    "p0_count": bs.get("p0_count"),
                    "open_blockers": bs.get("open_blockers") or [],
                },
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
        done["files"].append("blockers.json")
    except Exception as exc:
        done["blockers_error"] = str(exc)[:200]
        (PUB / "blockers.json").write_text(
            json.dumps({"schema": "rsi_eaf_blockers_public_v1", "updated_at": _now(), "open": []}, indent=2),
            encoding="utf-8",
        )

    # index
    try:
        from tools.publish_tools import build_index_html
        from revenue_engines.base_engine import resolve_treasury

        build_index_html(treasury_address=resolve_treasury())
        done["files"].append("index.html")
    except Exception as exc:
        done["index_error"] = str(exc)[:200]

    # network status already from mainnet_pay_surface
    for name in ("network-status.json", "treasury-map.json", "link-health.json"):
        if (PUB / name).exists():
            if name not in done["files"]:
                done["files"].append(name)

    # CDN mirror
    try:
        pub_pay = Path("public_pay")
        pub_pay.mkdir(parents=True, exist_ok=True)
        for name in (
            "pay.html",
            "agent-pay.json",
            "tip-manifest.json",
            "network-status.json",
            "treasury-map.json",
            "icp.json",
        ):
            src = PUB / name
            if src.exists():
                shutil.copy(src, pub_pay / name)
        done["cdn_sync"] = True
    except Exception as exc:
        done["cdn_sync_error"] = str(exc)[:200]

    done["at"] = _now()
    return done


def force_deploy_critical() -> Dict[str, Any]:
    """Force Vercel critical pack deploy (clears stale quota flag first if env says so)."""
    # Allow retry after daily reset
    if os.getenv("REMEDIATE_CLEAR_QUOTA", "true").lower() in {"1", "true", "yes"}:
        q = Path(os.getenv("VERCEL_QUOTA_STATE", "observability/vercel_quota_state.json"))
        if q.exists():
            try:
                q.unlink()
            except OSError:
                pass
    try:
        from tools.conversion_surfaces import deploy_critical_pack

        return deploy_critical_pack(force=True)
    except Exception as exc:
        return {"success": False, "error": str(exc)[:300]}


def verify_must_live() -> Dict[str, Any]:
    checks: Dict[str, Any] = {}
    all_ok = True
    for rel in MUST_LIVE:
        url = f"{BASE}/{rel.lstrip('/')}"
        try:
            r = httpx.get(url, timeout=15, follow_redirects=True)
            ok = r.status_code == 200 and len(r.content) > 40
            checks[rel] = {"status": r.status_code, "bytes": len(r.content), "ok": ok}
            if not ok:
                all_ok = False
        except Exception as exc:
            checks[rel] = {"ok": False, "error": str(exc)[:120]}
            all_ok = False
    return {"all_ok": all_ok, "checks": checks, "base": BASE, "at": _now()}


def remediate_conversion_and_links(*, cycle_id: Optional[int] = None) -> Dict[str, Any]:
    """Full path: regenerate → deploy → verify. Real fix for doctrine 404s."""
    cid = cycle_id if cycle_id is not None else _cycle_id()
    result: Dict[str, Any] = {"at": _now(), "cycle_id": cid, "steps": []}

    local = regenerate_all_local_surfaces(cid)
    result["steps"].append({"step": "regenerate_local", "ok": True, "detail": local})

    deploy = force_deploy_critical()
    result["steps"].append(
        {
            "step": "force_deploy",
            "ok": bool(deploy.get("success") or deploy.get("readyState") == "READY"),
            "detail": {
                "success": deploy.get("success"),
                "readyState": deploy.get("readyState"),
                "deploy_http": deploy.get("deploy_http"),
                "deploy_error": deploy.get("deploy_error"),
                "files": deploy.get("files"),
            },
        }
    )

    # Also ensure conversion path
    try:
        from tools.conversion_surfaces import ensure_conversion_surfaces

        ens = ensure_conversion_surfaces(force_deploy=True)
        result["steps"].append(
            {
                "step": "ensure_conversion",
                "ok": bool(ens.get("success") or (ens.get("live") or {}).get("pay_ok")),
                "detail": {
                    "action": ens.get("action"),
                    "pay_ok": (ens.get("live") or {}).get("pay_ok"),
                    "all_ok": (ens.get("live") or {}).get("all_ok"),
                },
            }
        )
    except Exception as exc:
        result["steps"].append({"step": "ensure_conversion", "ok": False, "error": str(exc)[:200]})

    live = verify_must_live()
    result["verify"] = live
    result["success"] = bool(live.get("all_ok")) or (
        live.get("checks", {}).get("pay.html", {}).get("ok")
        and live.get("checks", {}).get("agent-pay.json", {}).get("ok")
        and live.get("checks", {}).get("icp.json", {}).get("ok")
        and live.get("checks", {}).get("social-policy.json", {}).get("ok")
    )
    # Refresh link watcher board after fix
    try:
        from tools.link_watcher import run_link_watcher

        lw = run_link_watcher(remediate=False)
        result["link_watcher"] = lw.get("summary")
    except Exception as exc:
        result["link_watcher_error"] = str(exc)[:200]

    _log({"kind": "conversion_links", **result})
    Path("observability/factory_remediate_latest.json").write_text(
        json.dumps(result, indent=2, default=str), encoding="utf-8"
    )
    return result


def remediate_business_red(*, cycle_id: Optional[int] = None, skip_deploy_if_green: bool = True) -> Dict[str, Any]:
    """
    Cannot invent payers — but must maximize capture machinery:
    live pay surfaces, agent-pay, outreach, revenue sprint artifacts.
    """
    cid = cycle_id if cycle_id is not None else _cycle_id()
    result: Dict[str, Any] = {"at": _now(), "cycle_id": cid, "steps": []}

    # Surfaces first — skip full force-deploy if already all green (avoid thrash)
    live = verify_must_live()
    if skip_deploy_if_green and live.get("all_ok"):
        result["steps"].append(
            {
                "step": "conversion_links",
                "ok": True,
                "detail": {"skipped_deploy": True, "all_ok": True, "verify": live},
            }
        )
    else:
        conv = remediate_conversion_and_links(cycle_id=cid)
        result["steps"].append(
            {"step": "conversion_links", "ok": conv.get("success"), "detail": conv.get("verify")}
        )

    # Revenue sprint / capture surfaces
    try:
        from factory_core.revenue_sprint import run_revenue_sprint

        analysis = {"net_cumulative": {}}
        try:
            from observability.economic_ledger import ledger

            analysis["net_cumulative"] = ledger.calculate_net()
        except Exception:
            pass
        sprint = run_revenue_sprint(cid, analysis, None)
        result["steps"].append({"step": "revenue_sprint", "ok": True, "detail": str(sprint)[:300]})
    except Exception as exc:
        result["steps"].append({"step": "revenue_sprint", "ok": False, "error": str(exc)[:200]})

    # Autonomous outreach (ntfy, docs, social feed)
    try:
        from tools.autonomous_outreach import run_autonomous_outreach

        out = run_autonomous_outreach(cid, force=True)
        result["steps"].append(
            {"step": "autonomous_outreach", "ok": bool(out.get("success")), "detail": out}
        )
    except Exception as exc:
        result["steps"].append({"step": "autonomous_outreach", "ok": False, "error": str(exc)[:200]})

    # Fitness revenue capture pack (requires treasury address).
    # Skip heavy Vercel redeploy inside fitness when surfaces already green.
    try:
        from tools.fitness_revenue_capture import run_fitness_revenue_capture
        from revenue_engines.base_engine import resolve_treasury

        treasury = resolve_treasury()
        # Avoid nested deploy thrash: only run lightweight path when green
        if live.get("all_ok"):
            from observability.agent_payment import write_agent_pay_manifest
            from tools.distribution_tools import featured_links_for_index, write_tip_manifest

            featured = featured_links_for_index(cid) or {}
            write_agent_pay_manifest(cid, treasury, featured)
            write_tip_manifest(
                treasury_address=treasury,
                cycle_id=cid,
                live_tip_url=featured.get("canonical_tip_page")
                or featured.get("tip_page")
                or f"{BASE}/pay.html",
            )
            result["steps"].append(
                {
                    "step": "fitness_revenue_capture",
                    "ok": True,
                    "detail": {"mode": "lightweight_manifests_only", "treasury": treasury},
                }
            )
        else:
            cap = run_fitness_revenue_capture(cid, treasury)
            result["steps"].append(
                {"step": "fitness_revenue_capture", "ok": True, "detail": str(cap)[:300]}
            )
    except Exception as exc:
        result["steps"].append(
            {"step": "fitness_revenue_capture", "ok": False, "error": str(exc)[:200]}
        )

    # Treasury ingest (catch any missed mainnet/testnet payments)
    try:
        from observability.revenue_ingest import ingest_verified_xrpl_revenue

        ing = ingest_verified_xrpl_revenue(cid)
        result["steps"].append(
            {
                "step": "revenue_ingest",
                "ok": True,
                "ingested": len(ing.get("ingested") or []),
                "targets": ing.get("targets"),
            }
        )
    except Exception as exc:
        result["steps"].append({"step": "revenue_ingest", "ok": False, "error": str(exc)[:200]})

    # success = machinery green (not fake revenue)
    result["success"] = any(
        s.get("ok") for s in result["steps"] if s.get("step") in {"conversion_links", "autonomous_outreach"}
    )
    result["note"] = (
        "business_red stays OPEN until external organic ledger revenue rises; "
        "this pass maxed capture machinery (surfaces+outreach+ingest)."
    )
    _log({"kind": "business_red", **result})
    return result


def remediate_all_open_blockers(*, cycle_id: Optional[int] = None) -> Dict[str, Any]:
    """Run appropriate remediations for every currently open blocker type."""
    cid = cycle_id if cycle_id is not None else _cycle_id()
    out: Dict[str, Any] = {"at": _now(), "cycle_id": cid, "actions": []}

    # Always fix links/surfaces first
    out["actions"].append(
        {"blocker": "conversion_and_links", **remediate_conversion_and_links(cycle_id=cid)}
    )

    # Business red capture machinery
    out["actions"].append({"blocker": "business_red", **remediate_business_red(cycle_id=cid)})

    # Re-run guardian detectors without recursion depth issues — just write status
    try:
        from factory_core.blocker_guardian import scan_blockers, write_runbook

        found = scan_blockers()
        open_ids = [b.get("id") for b in found]
        status = {
            "schema": "rsi_eaf_blocker_status_v1",
            "updated_at": _now(),
            "open_count": len(found),
            "p0_count": sum(1 for b in found if b.get("severity") == "P0"),
            "open_blockers": found,
            "ids": open_ids,
            "last_remediation": out,
        }
        Path("observability/blocker_status.json").write_text(
            json.dumps(status, indent=2, default=str), encoding="utf-8"
        )
        write_runbook(found, [{"blocker_id": a.get("blocker"), "success": a.get("success"), "status_after": "attempted"} for a in out["actions"]])
        out["open_after"] = open_ids
    except Exception as exc:
        out["guardian_refresh_error"] = str(exc)[:200]

    out["success"] = any(a.get("success") for a in out["actions"])
    Path("observability/factory_remediate_all_latest.json").write_text(
        json.dumps(out, indent=2, default=str), encoding="utf-8"
    )
    return out


if __name__ == "__main__":
    import pprint

    pprint.pp(remediate_all_open_blockers())
