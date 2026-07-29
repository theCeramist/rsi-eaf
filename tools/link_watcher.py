"""
Factory link watcher — never share a 404.

Collects every URL the factory advertises on social / pay / discovery surfaces,
probes them continuously, remediates when down, and publishes a public health
board. Social posters must call `assert_cta_links_ok()` before posting.

Surfaces:
  observability/link_watcher_latest.json
  observability/link_watcher.jsonl
  published/link-health.json
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse

import httpx

OBS = Path(os.getenv("OBSERVABILITY_DIR", "observability"))
PUB = Path(os.getenv("PUBLISHED_DIR", "published"))
LATEST = OBS / "link_watcher_latest.json"
LOG = OBS / "link_watcher.jsonl"
PUB_HEALTH = PUB / "link-health.json"
DEAD_POST_BLOCK = OBS / "link_watcher_block_posts.flag"

BASE = os.getenv("FACTORY_PUBLIC_BASE_URL", "https://published-zeta.vercel.app").rstrip("/")
CDN_PAY = os.getenv(
    "MAINNET_PAY_CDN",
    "https://cdn.jsdelivr.net/gh/theCeramist/rsi-eaf@master/public_pay",
).rstrip("/")
AETHERFORGE = os.getenv("AETHERFORGE_URL", "https://aetherforge.world").rstrip("/")
TIMEOUT = float(os.getenv("LINK_WATCHER_TIMEOUT_SEC", "8"))
MIN_BYTES = int(os.getenv("LINK_WATCHER_MIN_BYTES", "40"))

# Severity: critical = must never be posted if down; high = primary discovery; medium = secondary
URL_CATALOG: List[Dict[str, str]] = [
    # Primary conversion (both Vercel + CDN so we see which is dead)
    {"id": "pay_vercel", "url": f"{BASE}/pay.html", "severity": "critical", "group": "pay"},
    {"id": "agent_pay_vercel", "url": f"{BASE}/agent-pay.json", "severity": "critical", "group": "pay"},
    {"id": "pay_cdn", "url": f"{CDN_PAY}/pay.html", "severity": "critical", "group": "pay_cdn"},
    {"id": "agent_pay_cdn", "url": f"{CDN_PAY}/agent-pay.json", "severity": "critical", "group": "pay_cdn"},
    {"id": "tip_manifest_cdn", "url": f"{CDN_PAY}/tip-manifest.json", "severity": "high", "group": "pay_cdn"},
    {"id": "network_status_cdn", "url": f"{CDN_PAY}/network-status.json", "severity": "high", "group": "pay_cdn"},
    # Vercel discovery
    {"id": "tip_manifest", "url": f"{BASE}/tip-manifest.json", "severity": "high", "group": "vercel"},
    {"id": "icp", "url": f"{BASE}/icp.json", "severity": "high", "group": "vercel"},
    {"id": "free_sample", "url": f"{BASE}/free-sample.json", "severity": "medium", "group": "vercel"},
    {"id": "free_ads", "url": f"{BASE}/free-ads.html", "severity": "medium", "group": "vercel"},
    {"id": "index", "url": f"{BASE}/", "severity": "high", "group": "vercel"},
    {"id": "x402", "url": f"{BASE}/.well-known/x402.json", "severity": "high", "group": "vercel"},
    {"id": "social_policy", "url": f"{BASE}/social-policy.json", "severity": "medium", "group": "vercel"},
    {"id": "social_learning", "url": f"{BASE}/social-learning.json", "severity": "medium", "group": "vercel"},
    {"id": "network_status", "url": f"{BASE}/network-status.json", "severity": "medium", "group": "vercel"},
    {"id": "blockers", "url": f"{BASE}/blockers.json", "severity": "medium", "group": "vercel"},
    # External
    {"id": "aetherforge", "url": f"{AETHERFORGE}/", "severity": "high", "group": "external"},
    {"id": "github_repo", "url": "https://github.com/theCeramist/rsi-eaf", "severity": "medium", "group": "external"},
    {"id": "github_bounty", "url": "https://github.com/theCeramist/rsi-eaf/issues/178", "severity": "low", "group": "external"},
]

URL_RE = re.compile(r"https?://[^\s<>\"')\]]+", re.I)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(rec: Dict[str, Any]) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, default=str) + "\n")


def _write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


# Paths we actively advertise (not one-off cycle HTML that rot on free-tier CDN)
_STABLE_PATH_RE = re.compile(
    r"/(pay\.html|agent-pay\.json|tip-manifest\.json|icp\.json|free-ads\.html|"
    r"free-sample\.json|network-status\.json|social-policy\.json|social-learning\.json|"
    r"blockers\.json|link-health\.json|treasury-map\.json|"
    r"\.well-known/x402\.json|public_pay/)(?:\?|$)",
    re.I,
)


def _is_stable_factory_url(url: str) -> bool:
    """Ignore per-cycle tip-cycle-N-*.html noise; keep stable conversion paths."""
    try:
        p = urlparse(url)
        path = p.path or ""
        host = (p.netloc or "").lower()
        if any(x in host for x in ("twitter.com", "x.com", "api.twitter", "t.co", "github.com/")):
            # github issues/repo OK as catalog already lists them; skip deep junk
            if "github.com" in host and "/issues/" not in path and path.count("/") > 3:
                return False
        # Drop dated cycle assets
        if re.search(r"cycle-\d{3,}|tip-cycle-\d|briefing-cycle-\d|micro-tool-cycle-\d", path, re.I):
            return False
        if "published-zeta.vercel.app" in host or "jsdelivr.net" in host or "aetherforge" in host:
            return bool(_STABLE_PATH_RE.search(path) or path in {"", "/"})
        if "jsdelivr.net" in host and "public_pay" in path:
            return True
        return bool(_STABLE_PATH_RE.search(path))
    except Exception:
        return False


def collect_urls_from_artifacts() -> List[Dict[str, str]]:
    """Harvest stable URLs from recent X posts and key JSON (no cycle HTML spam)."""
    found: List[Dict[str, str]] = []
    seen: Set[str] = set()

    def add(url: str, source: str, severity: str = "medium") -> None:
        url = (url or "").strip().rstrip(".,);]")
        if not url.startswith("http") or url in seen:
            return
        host = urlparse(url).netloc.lower()
        if any(x in host for x in ("twitter.com", "x.com", "api.twitter", "t.co")):
            return
        if not _is_stable_factory_url(url):
            return
        seen.add(url)
        found.append(
            {
                "id": f"artifact_{len(found)}",
                "url": url,
                "severity": severity,
                "group": "artifact",
                "source": source,
            }
        )

    # Only high-signal JSON (not every services-cycle-*.json)
    for name in (
        "agent-pay.json",
        "tip-manifest.json",
        "free-ads.json",
        "network-status.json",
        "icp.json",
        "social-policy.json",
        "link-health.json",
    ):
        path = PUB / name
        if path.exists():
            try:
                for m in URL_RE.findall(path.read_text(encoding="utf-8", errors="ignore")):
                    add(m, name, "high" if "pay" in name else "medium")
            except OSError:
                pass

    # X agent recent post texts — these ARE what users click
    x_state = OBS / "x_agent_state.json"
    if x_state.exists():
        try:
            st = json.loads(x_state.read_text(encoding="utf-8"))
            for t in (st.get("recent_post_texts") or [])[-30:]:
                for m in URL_RE.findall(str(t)):
                    # Anything we actually posted is critical if it's a factory URL
                    sev = "critical" if "pay" in m.lower() else "high"
                    add(m, "x_agent_recent", sev)
        except (json.JSONDecodeError, OSError):
            pass

    return found


def catalog_urls() -> List[Dict[str, str]]:
    """Full catalog = static + dynamic harvest (deduped by URL)."""
    by_url: Dict[str, Dict[str, str]] = {}
    for item in URL_CATALOG:
        by_url[item["url"]] = dict(item)
    for item in collect_urls_from_artifacts():
        if item["url"] not in by_url:
            by_url[item["url"]] = item
        else:
            # escalate severity if artifact says critical
            cur = by_url[item["url"]]
            order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
            if order.get(item.get("severity", "medium"), 9) < order.get(cur.get("severity", "medium"), 9):
                cur["severity"] = item["severity"]
    return list(by_url.values())


def probe_url(url: str, timeout: float = TIMEOUT) -> Dict[str, Any]:
    """HTTP GET probe with status, bytes, latency."""
    t0 = time.time()
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            # Prefer GET — some CDNs mishandle HEAD
            r = client.get(url, headers={"User-Agent": "RSI-EAF-LinkWatcher/1.0"})
            ms = int((time.time() - t0) * 1000)
            body = r.content or b""
            ok = r.status_code == 200 and len(body) >= MIN_BYTES
            # soft 404 pages sometimes return 200 with tiny body
            text_snip = body[:200].decode("utf-8", errors="ignore").lower()
            if ok and ("not found" in text_snip and len(body) < 500):
                ok = False
            return {
                "url": url,
                "ok": ok,
                "status": r.status_code,
                "bytes": len(body),
                "ms": ms,
                "final_url": str(r.url),
            }
    except Exception as exc:
        return {
            "url": url,
            "ok": False,
            "status": None,
            "bytes": 0,
            "ms": int((time.time() - t0) * 1000),
            "error": f"{type(exc).__name__}:{exc}"[:200],
        }


def probe_all(urls: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
    items = urls or catalog_urls()
    checks: List[Dict[str, Any]] = []
    for item in items:
        result = probe_url(item["url"])
        result.update(
            {
                "id": item.get("id"),
                "severity": item.get("severity", "medium"),
                "group": item.get("group", "unknown"),
                "source": item.get("source"),
            }
        )
        checks.append(result)

    failed = [c for c in checks if not c.get("ok")]
    critical_failed = [c for c in failed if c.get("severity") == "critical"]
    high_failed = [c for c in failed if c.get("severity") == "high"]

    # Pay group health: at least one of vercel pay or cdn pay must work
    pay_ok = any(
        c.get("ok") and c.get("group") in {"pay", "pay_cdn"} and "pay.html" in (c.get("url") or "")
        for c in checks
    )
    agent_pay_ok = any(
        c.get("ok") and "agent-pay" in (c.get("url") or "") for c in checks
    )

    summary = {
        "total": len(checks),
        "ok": sum(1 for c in checks if c.get("ok")),
        "failed": len(failed),
        "critical_failed": len(critical_failed),
        "high_failed": len(high_failed),
        "pay_surface_ok": pay_ok,
        "agent_pay_ok": agent_pay_ok,
        "all_critical_ok": len(critical_failed) == 0 and pay_ok and agent_pay_ok,
        "safe_to_post": pay_ok and agent_pay_ok,
    }
    return {
        "schema": "rsi_eaf_link_watcher_v1",
        "ts": _now(),
        "summary": summary,
        "checks": checks,
        "failed_urls": [c["url"] for c in failed],
        "critical_failed_urls": [c["url"] for c in critical_failed],
    }


def remediate_failures(report: Dict[str, Any]) -> Dict[str, Any]:
    """Attempt to restore down surfaces without human input — real force-deploy, not just notes."""
    actions: List[Dict[str, Any]] = []
    failed = {c["url"]: c for c in report.get("checks") or [] if not c.get("ok")}

    # Prefer aggressive factory_remediate when anything failed (incl. doctrine 404s)
    if failed:
        try:
            from tools.factory_remediate import remediate_conversion_and_links

            r = remediate_conversion_and_links()
            actions.append(
                {
                    "action": "factory_remediate.remediate_conversion_and_links",
                    "success": bool(r.get("success")),
                    "detail": {
                        "all_ok": (r.get("verify") or {}).get("all_ok"),
                        "steps": [
                            {"step": s.get("step"), "ok": s.get("ok")}
                            for s in (r.get("steps") or [])
                        ],
                    },
                }
            )
            return {
                "actions": actions,
                "success": bool(r.get("success")),
                "failed_before": list(failed.keys()),
            }
        except Exception as exc:
            actions.append(
                {
                    "action": "factory_remediate.remediate_conversion_and_links",
                    "success": False,
                    "error": str(exc)[:200],
                }
            )

    # Fallback: local pay pack + soft ensure (when no failures or remediate import failed)
    try:
        from tools.mainnet_pay_surface import write_mainnet_pay_surface
        from factory_core.state import FactoryState

        cid = int(FactoryState().current_cycle or 0)
        surface = write_mainnet_pay_surface(cid)
        actions.append({"action": "write_mainnet_pay_surface", "success": True, "detail": surface})
    except Exception as exc:
        actions.append({"action": "write_mainnet_pay_surface", "success": False, "error": str(exc)[:200]})

    try:
        from tools.conversion_surfaces import ensure_conversion_surfaces

        r = ensure_conversion_surfaces(force_deploy=bool(failed))
        actions.append(
            {
                "action": "ensure_conversion_surfaces",
                "success": bool(r.get("success")),
                "detail": {
                    "action": r.get("action"),
                    "pay_ok": (r.get("live") or {}).get("pay_ok"),
                    "error": r.get("error"),
                },
            }
        )
    except Exception as exc:
        actions.append({"action": "ensure_conversion_surfaces", "success": False, "error": str(exc)[:200]})

    # 2) Sync public_pay/ for CDN from local published
    try:
        pub_pay = Path("public_pay")
        pub_pay.mkdir(parents=True, exist_ok=True)
        for name in (
            "pay.html",
            "agent-pay.json",
            "tip-manifest.json",
            "network-status.json",
            "treasury-map.json",
        ):
            src = PUB / name
            if src.exists():
                (pub_pay / name).write_bytes(src.read_bytes())
        actions.append({"action": "sync_public_pay", "success": True})
    except Exception as exc:
        actions.append({"action": "sync_public_pay", "success": False, "error": str(exc)[:200]})

    # 3) If Vercel pay is down but CDN ok — rewrite social env preference already CDN
    vercel_pay_down = any(
        (not c.get("ok")) and c.get("group") == "pay" for c in report.get("checks") or []
    )
    cdn_pay_up = any(
        c.get("ok") and c.get("group") == "pay_cdn" for c in report.get("checks") or []
    )
    if vercel_pay_down and cdn_pay_up:
        os.environ["MAINNET_PAY_CDN"] = CDN_PAY
        os.environ["FACTORY_FORCE_CDN_CTA"] = "true"
        actions.append(
            {
                "action": "force_cdn_cta",
                "success": True,
                "detail": "Vercel pay down — social must use CDN",
            }
        )

    # 4) Optional git push public_pay if env allows and CDN stale
    if os.getenv("LINK_WATCHER_AUTOPUSH", "false").lower() in {"1", "true", "yes"}:
        try:
            import subprocess

            subprocess.run(
                ["git", "add", "public_pay"],
                cwd=str(Path(".").resolve()),
                capture_output=True,
                timeout=30,
            )
            # only commit if changes
            st = subprocess.run(
                ["git", "status", "--porcelain", "public_pay"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if st.stdout.strip():
                subprocess.run(
                    ["git", "commit", "-m", "chore: link-watcher refresh public_pay CDN"],
                    capture_output=True,
                    timeout=30,
                )
                subprocess.run(
                    ["git", "push", "origin", "HEAD"],
                    capture_output=True,
                    timeout=60,
                )
                actions.append({"action": "git_push_public_pay", "success": True})
            else:
                actions.append({"action": "git_push_public_pay", "success": True, "detail": "no_changes"})
        except Exception as exc:
            actions.append({"action": "git_push_public_pay", "success": False, "error": str(exc)[:200]})

    # 5) Re-probe criticals after remediation
    critical_ids = [u for u in URL_CATALOG if u.get("severity") == "critical"]
    recheck = probe_all(critical_ids)
    return {
        "actions": actions,
        "recheck": recheck.get("summary"),
        "recheck_failed": recheck.get("critical_failed_urls"),
        "at": _now(),
    }


def preferred_cta_urls() -> Dict[str, str]:
    """URLs social agents should use right now (CDN preferred if Vercel dead)."""
    report = probe_all(
        [u for u in URL_CATALOG if u.get("group") in {"pay", "pay_cdn"}]
    )
    by_id = {c.get("id"): c for c in report.get("checks") or []}
    pay = CDN_PAY + "/pay.html"
    agent = CDN_PAY + "/agent-pay.json"
    if by_id.get("pay_vercel", {}).get("ok") and not os.getenv("FACTORY_FORCE_CDN_CTA"):
        # Prefer CDN for mainnet always if configured
        try:
            from factory_core.xrpl_network import revenue_network

            if revenue_network() != "mainnet" and by_id.get("pay_vercel", {}).get("ok"):
                pay = f"{BASE}/pay.html"
                agent = f"{BASE}/agent-pay.json"
        except Exception:
            pass
    if by_id.get("pay_cdn", {}).get("ok"):
        pay = CDN_PAY + "/pay.html"
    elif by_id.get("pay_vercel", {}).get("ok"):
        pay = f"{BASE}/pay.html"
    if by_id.get("agent_pay_cdn", {}).get("ok"):
        agent = CDN_PAY + "/agent-pay.json"
    elif by_id.get("agent_pay_vercel", {}).get("ok"):
        agent = f"{BASE}/agent-pay.json"
    return {"pay": pay, "agent_pay": agent, "base": BASE, "cdn": CDN_PAY}


def assert_cta_links_ok(*, force_refresh: bool = False) -> Dict[str, Any]:
    """
    Gate for social posters. Returns {ok, pay_url, agent_pay_url, block_reason}.
    If not ok, posts MUST NOT include dead pay CTAs.
    """
    report = run_link_watcher(remediate=True) if force_refresh else probe_all(
        [u for u in URL_CATALOG if u.get("severity") in {"critical", "high"}]
    )
    if force_refresh:
        summary = (report.get("probe") or report).get("summary") or report.get("summary") or {}
        full = report
    else:
        summary = report.get("summary") or {}
        full = report

    ctas = preferred_cta_urls()
    # Verify preferred CTAs one more time
    pay_probe = probe_url(ctas["pay"])
    agent_probe = probe_url(ctas["agent_pay"])
    ok = bool(pay_probe.get("ok") and agent_probe.get("ok"))
    out = {
        "ok": ok,
        "pay_url": ctas["pay"],
        "agent_pay_url": ctas["agent_pay"],
        "pay_probe": pay_probe,
        "agent_probe": agent_probe,
        "summary": summary,
        "block_reason": None if ok else "critical_cta_down",
        "at": _now(),
    }
    if ok:
        if DEAD_POST_BLOCK.exists():
            DEAD_POST_BLOCK.unlink(missing_ok=True)
    else:
        DEAD_POST_BLOCK.write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out


def run_link_watcher(*, remediate: bool = True) -> Dict[str, Any]:
    """Full scan → optional remediate → publish health board."""
    probe = probe_all()
    remediation = None
    if remediate and (
        not probe["summary"]["safe_to_post"]
        or probe["summary"]["failed"] > 0
    ):
        remediation = remediate_failures(probe)
        # final probe after remediation
        probe = probe_all()

    result = {
        "schema": "rsi_eaf_link_watcher_v1",
        "ts": _now(),
        "probe": probe,
        "summary": probe.get("summary"),
        "remediation": remediation,
        "preferred_cta": preferred_cta_urls(),
    }
    _write(LATEST, result)
    # Public honesty board
    public = {
        "schema": "rsi_eaf_link_health_v1",
        "updated_at": _now(),
        "safe_to_post": probe["summary"]["safe_to_post"],
        "pay_surface_ok": probe["summary"]["pay_surface_ok"],
        "agent_pay_ok": probe["summary"]["agent_pay_ok"],
        "total": probe["summary"]["total"],
        "ok": probe["summary"]["ok"],
        "failed": probe["summary"]["failed"],
        "failed_urls": probe.get("failed_urls") or [],
        "critical_failed_urls": probe.get("critical_failed_urls") or [],
        "preferred_cta": result["preferred_cta"],
        "note": "Factory must not post CTAs when safe_to_post is false",
    }
    _write(PUB_HEALTH, public)
    _log({"ts": _now(), "summary": probe["summary"], "remediated": bool(remediation)})

    # Posting block flag
    if probe["summary"]["safe_to_post"]:
        DEAD_POST_BLOCK.unlink(missing_ok=True)
    else:
        DEAD_POST_BLOCK.write_text(json.dumps(public, indent=2), encoding="utf-8")

    return result


if __name__ == "__main__":
    import pprint

    pprint.pp(run_link_watcher(remediate=True))
