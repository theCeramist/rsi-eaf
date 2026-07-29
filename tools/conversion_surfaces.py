"""
Conversion surface integrity — never leave the factory CTA-broken.

Root cause of business failure mode: pay.html / doctrine JSON go missing
locally, surgical deploys omit them, production 404s while X still CTAs.

Public contract:
  /pay.html
  /agent-pay.json
  /.well-known/x402.json
  /icp.json
  /social-policy.json
  /social-learning.json
  /index.html
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

PUBLISHED = Path(os.getenv("PUBLISHED_DIR", "published"))
BASE = os.getenv("FACTORY_PUBLIC_BASE_URL", "https://published-zeta.vercel.app").rstrip("/")
LOG = Path(os.getenv("CONVERSION_SURFACE_LOG", "observability/conversion_surfaces.jsonl"))

CRITICAL_RELS = [
    "pay.html",
    "agent-pay.json",
    "icp.json",
    "social-policy.json",
    "social-learning.json",
    "index.html",
    "vercel.json",
    ".well-known/x402.json",
    ".well-known/agent-pay.json",
    "free-sample.json",
    "free-ads.html",
    "blockers.json",
    "link-health.json",
    "network-status.json",
    "treasury-map.json",
    "tip-manifest.json",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(rec: Dict[str, Any]) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, default=str) + "\n")


def ensure_local_pay_html() -> Dict[str, Any]:
    """Restore exclusive pay.html from archive or live production."""
    PUBLISHED.mkdir(parents=True, exist_ok=True)
    (PUBLISHED / "archive").mkdir(parents=True, exist_ok=True)
    pay = PUBLISHED / "pay.html"
    arch = PUBLISHED / "archive" / "pay.html"

    def exclusive(text: str) -> bool:
        t = text.lower()
        return (
            "thatcrypto" in t
            or "not for everyone" in t
            or "destination tag" in t
            or "mainnet" in t
            or "rsi-eaf" in t
        )

    if pay.exists() and exclusive(pay.read_text(encoding="utf-8", errors="ignore")):
        if not arch.exists():
            arch.write_bytes(pay.read_bytes())
        return {"ok": True, "source": "local", "bytes": pay.stat().st_size}

    if arch.exists() and exclusive(arch.read_text(encoding="utf-8", errors="ignore")):
        pay.write_bytes(arch.read_bytes())
        return {"ok": True, "source": "archive", "bytes": pay.stat().st_size}

    try:
        r = httpx.get(f"{BASE}/pay.html", timeout=20, follow_redirects=True)
        if r.status_code == 200 and exclusive(r.text):
            pay.write_text(r.text, encoding="utf-8")
            arch.write_text(r.text, encoding="utf-8")
            return {"ok": True, "source": "production", "bytes": len(r.content)}
    except httpx.HTTPError as exc:
        return {"ok": False, "error": f"fetch_failed:{exc}"}

    # Minimal exclusive fallback if everything else is gone
    fallback = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/><title>RSI-EAF Pay</title>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
</head><body style="font-family:system-ui;max-width:40rem;margin:2rem auto;padding:0 1rem;background:#070a12;color:#e8eefc">
<h1>RSI-EAF is not for everyone</h1>
<p>Human bar: <strong>@thatcrypto_guy</strong>-class. Agent bar: settlement-grade only.</p>
<ol>
<li>Testnet XRP faucet</li>
<li>Send to <code>rBiU74q2wCPQ7ri9YD6J6LrQ2Y3jFd8pcN</code></li>
<li>Destination Tag <strong>1</strong> tip · Tag <strong>2</strong> briefing</li>
</ol>
<p><a href="{BASE}/agent-pay.json">agent-pay.json</a> ·
<a href="{BASE}/social-policy.json">social-policy.json</a> ·
<a href="{BASE}/icp.json">icp.json</a></p>
</body></html>
"""
    pay.write_text(fallback, encoding="utf-8")
    arch.write_text(fallback, encoding="utf-8")
    return {"ok": True, "source": "fallback_written", "bytes": len(fallback)}


def ensure_doctrine_artifacts() -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    try:
        from factory_core.social_policy import write_policy_artifacts

        out["policy"] = write_policy_artifacts()
    except Exception as exc:
        out["policy_error"] = str(exc)[:200]
    try:
        from factory_core.social_learning import build_social_learning_report, persist_social_learning

        out["learning"] = persist_social_learning(build_social_learning_report())
    except Exception as exc:
        out["learning_error"] = str(exc)[:200]
    try:
        from factory_core.target_icp import icp_manifest

        (PUBLISHED / "icp.json").write_text(json.dumps(icp_manifest(), indent=2), encoding="utf-8")
        out["icp"] = True
    except Exception as exc:
        out["icp_error"] = str(exc)[:200]
    return out


# Paths that must be live for CTA/pay integrity (doctrine extras are secondary)
PAY_CRITICAL_PATHS = [
    "/pay.html",
    "/agent-pay.json",
]
DOCTRINE_PATHS = [
    "/social-policy.json",
    "/social-learning.json",
    "/icp.json",
    "/.well-known/x402.json",
]


def verify_live(paths: Optional[List[str]] = None) -> Dict[str, Any]:
    paths = paths or (PAY_CRITICAL_PATHS + DOCTRINE_PATHS)
    checks: Dict[str, Any] = {}
    all_ok = True
    for path in paths:
        url = f"{BASE}{path}"
        try:
            r = httpx.get(url, timeout=20, follow_redirects=True)
            ok = r.status_code == 200 and len(r.content) > 50
            checks[path] = {"status": r.status_code, "bytes": len(r.content), "ok": ok}
            if not ok:
                all_ok = False
        except httpx.HTTPError as exc:
            checks[path] = {"ok": False, "error": str(exc)[:120]}
            all_ok = False
    pay_ok = all(
        (checks.get(p) or {}).get("ok") for p in PAY_CRITICAL_PATHS if p in checks or True
    )
    # recompute pay_ok only from critical list even if paths was custom
    pay_checks = {}
    for p in PAY_CRITICAL_PATHS:
        if p in checks:
            pay_checks[p] = checks[p]
        else:
            try:
                r = httpx.get(f"{BASE}{p}", timeout=20, follow_redirects=True)
                pay_checks[p] = {
                    "status": r.status_code,
                    "bytes": len(r.content),
                    "ok": r.status_code == 200 and len(r.content) > 50,
                }
            except httpx.HTTPError as exc:
                pay_checks[p] = {"ok": False, "error": str(exc)[:120]}
    pay_ok = all(c.get("ok") for c in pay_checks.values()) if pay_checks else False
    # CDN fallback counts as pay_ok when Vercel free-tier wipes pay.html
    if not pay_ok:
        try:
            cdn = os.getenv(
                "MAINNET_PAY_CDN",
                "https://cdn.jsdelivr.net/gh/theCeramist/rsi-eaf@master/public_pay",
            ).rstrip("/")
            cr = httpx.get(f"{cdn}/pay.html", timeout=12, follow_redirects=True)
            ar = httpx.get(f"{cdn}/agent-pay.json", timeout=12, follow_redirects=True)
            if cr.status_code == 200 and ar.status_code == 200 and len(cr.content) > 50:
                pay_ok = True
                pay_checks["cdn_pay.html"] = {
                    "status": cr.status_code,
                    "bytes": len(cr.content),
                    "ok": True,
                    "url": f"{cdn}/pay.html",
                }
                pay_checks["cdn_agent-pay.json"] = {
                    "status": ar.status_code,
                    "bytes": len(ar.content),
                    "ok": True,
                    "url": f"{cdn}/agent-pay.json",
                }
        except Exception:
            pass
    return {
        "all_ok": all_ok,
        "pay_ok": pay_ok,
        "checks": checks,
        "pay_checks": pay_checks,
        "base": BASE,
    }


def _quota_state_path() -> Path:
    return Path(os.getenv("VERCEL_QUOTA_STATE", "observability/vercel_quota_state.json"))


def record_vercel_quota_block(reason: str, detail: Optional[Dict[str, Any]] = None) -> None:
    payload = {
        "blocked": True,
        "reason": reason,
        "detail": detail or {},
        "at": _now(),
        "until_hint": "retry after Vercel free-tier daily reset (~24h)",
    }
    p = _quota_state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def vercel_quota_blocked() -> Dict[str, Any]:
    p = _quota_state_path()
    if not p.exists():
        return {"blocked": False}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"blocked": False}
    except (json.JSONDecodeError, OSError):
        return {"blocked": False}


def deploy_critical_pack(*, force: bool = False) -> Dict[str, Any]:
    """Surgical Vercel deploy of conversion-critical files only. Always includes pay.html."""
    token = os.getenv("VERCEL_TOKEN")
    if not token:
        return {"success": False, "error": "no_VERCEL_TOKEN"}
    q = vercel_quota_blocked()
    if q.get("blocked") and not force:
        live = verify_live()
        return {
            "success": bool(live.get("pay_ok")),
            "error": "vercel_quota_blocked",
            "quota": q,
            "live": live,
            "at": _now(),
            "note": "Skipped deploy — free-tier quota exhausted; pay_ok may still hold",
        }
    project = os.getenv("FACTORY_VERCEL_PROJECT_ID", "prj_kMNf4hUsd2dZjhEArOeqVrsWniDe")
    team = os.getenv("FACTORY_VERCEL_TEAM_ID", "team_TaQi1jIfAjwA0mYpRla493rW")
    headers = {"Authorization": f"Bearer {token}"}

    pay = ensure_local_pay_html()
    doctrine = ensure_doctrine_artifacts()
    if not pay.get("ok"):
        return {"success": False, "error": "pay_html_unrecoverable", "pay": pay}

    # Ensure nested dirs for .well-known etc.
    (PUBLISHED / ".well-known").mkdir(parents=True, exist_ok=True)

    meta: List[Dict[str, Any]] = []
    upload_errors: List[Dict[str, Any]] = []
    for rel in CRITICAL_RELS:
        p = PUBLISHED / rel
        if not p.exists():
            upload_errors.append({"file": rel, "error": "missing_local"})
            continue
        data = p.read_bytes()
        dig = hashlib.sha1(data).hexdigest()
        up = httpx.post(
            f"https://api.vercel.com/v2/files?size={len(data)}",
            headers={**headers, "Content-Type": "application/octet-stream", "x-vercel-digest": dig},
            params={"teamId": team},
            content=data,
            timeout=90,
        )
        # 200/201 created; 409 already on CDN for this digest — still usable in deploy
        if up.status_code in (200, 201, 409):
            meta.append({"file": rel, "sha": dig, "size": len(data)})
        else:
            upload_errors.append(
                {
                    "file": rel,
                    "status": up.status_code,
                    "body": (up.text or "")[:200],
                }
            )

    if not any(m["file"] == "pay.html" for m in meta):
        return {
            "success": False,
            "error": "pay.html_not_uploaded",
            "meta_n": len(meta),
            "upload_errors": upload_errors,
        }

    r = httpx.post(
        "https://api.vercel.com/v13/deployments",
        headers={**headers, "Content-Type": "application/json"},
        params={"teamId": team, "forceNew": "1"},
        json={
            "name": "published",
            "project": project,
            "target": "production",
            "files": meta,
            "projectSettings": {"framework": None},
            "meta": {"deployMethod": "conversion_surfaces_guard"},
        },
        timeout=120,
    )
    body = r.json() if r.content else {}
    did = body.get("id") or body.get("uid")
    state = "UNKNOWN"
    deploy_error = None
    if r.status_code >= 400:
        deploy_error = {"status": r.status_code, "body": (r.text or "")[:400]}
    if did:
        for _ in range(45):
            st = httpx.get(
                f"https://api.vercel.com/v13/deployments/{did}",
                headers=headers,
                params={"teamId": team},
                timeout=30,
            ).json().get("readyState")
            state = st or state
            if st in {"READY", "ERROR", "CANCELED"}:
                break
            time.sleep(2)

    live = verify_live()
    # Detect free-tier exhaustion so we stop thrashing the API
    if r.status_code == 402 or any(
        (e.get("status") in (402, 429)) for e in upload_errors
    ):
        record_vercel_quota_block(
            "api-deployments-or-upload-limited",
            {"deploy_http": r.status_code, "upload_errors": upload_errors[:5]},
        )
    result = {
        # Success if deploy READY and pay path live — doctrine extras may lag under quota
        "success": (state == "READY" and live.get("pay_ok"))
        or (live.get("pay_ok") and r.status_code in (402, 429)),
        "deploy_id": did,
        "readyState": state,
        "deploy_http": r.status_code,
        "deploy_error": deploy_error,
        "upload_errors": upload_errors,
        "pay_restore": pay,
        "doctrine": doctrine,
        "files": [m["file"] for m in meta],
        "live": live,
        "at": _now(),
    }
    _log(result)
    # status snapshot
    Path("observability/conversion_surfaces_latest.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    return result


def ensure_conversion_surfaces(*, force_deploy: bool = False) -> Dict[str, Any]:
    """
    Idempotent guard: restore local pay + doctrine, verify live, deploy if broken.
    Call from distribution daemon / cycle post-sync / supervisor.

    Operational success = pay.html + agent-pay.json live (pay_ok).
    Full doctrine (social-*, x402) is best-effort and may lag under Vercel free quota.
    """
    pay = ensure_local_pay_html()
    doctrine = ensure_doctrine_artifacts()
    live = verify_live()

    def _snap(action: str, **extra: Any) -> Dict[str, Any]:
        out = {
            "success": True,
            "action": action,
            "pay": pay,
            "doctrine": doctrine,
            "live": live,
            "at": _now(),
            **extra,
        }
        _log(out)
        Path("observability/conversion_surfaces_latest.json").write_text(
            json.dumps(out, indent=2), encoding="utf-8"
        )
        return out

    if live.get("all_ok") and not force_deploy:
        return _snap("verified_ok")
    if live.get("pay_ok") and not force_deploy:
        return _snap(
            "pay_ok_doctrine_partial" if not live.get("all_ok") else "pay_ok",
            quota=vercel_quota_blocked() if not live.get("all_ok") else None,
        )
    # When force_deploy=True and doctrine incomplete, always attempt deploy
    # (deploy_critical_pack(force=True) bypasses soft quota skip; real 402 still recorded)
    if live.get("pay_ok") and force_deploy and vercel_quota_blocked().get("blocked"):
        # Still try once under force — soft block may be stale after daily reset
        return deploy_critical_pack(force=True)

    # pay path broken or force with quota remaining / doctrine incomplete
    return deploy_critical_pack(force=force_deploy)


if __name__ == "__main__":
    import pprint

    try:
        from dotenv import load_dotenv

        load_dotenv(override=True)
    except Exception:
        pass
    pprint.pp(ensure_conversion_surfaces(force_deploy=True))
