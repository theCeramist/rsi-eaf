"""
Publishing tools — deploy /published assets to a verifiable live URL.
"""

import hashlib
import json
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from config.integration import FACTORY_PUBLIC_BASE_URL as _DEFAULT_BASE_URL
from config.integration import VERCEL_DEPLOY_COOLDOWN_MINUTES as _DEFAULT_COOLDOWN

PUBLISHED_DIR = Path(os.getenv("PUBLISHED_DIR", "published"))
FACTORY_PUBLIC_BASE_URL = os.getenv("FACTORY_PUBLIC_BASE_URL", _DEFAULT_BASE_URL).rstrip("/")
VERCEL_DEPLOY = os.getenv("VERCEL_DEPLOY", "true").lower() in {"1", "true", "yes"}
VERCEL_DEPLOY_COOLDOWN_MINUTES = int(os.getenv("VERCEL_DEPLOY_COOLDOWN_MINUTES", str(_DEFAULT_COOLDOWN)))
VERCEL_TOKEN = os.getenv("VERCEL_TOKEN")
FACTORY_VERCEL_PROJECT_ID = os.getenv(
    "FACTORY_VERCEL_PROJECT_ID", "prj_kMNf4hUsd2dZjhEArOeqVrsWniDe"
).strip()
FACTORY_VERCEL_TEAM_ID = os.getenv("FACTORY_VERCEL_TEAM_ID", "team_TaQi1jIfAjwA0mYpRla493rW").strip()
LAST_DEPLOY_FILE = PUBLISHED_DIR / ".last_vercel_deploy"
QUOTA_STATE_FILE = Path(os.getenv("VERCEL_QUOTA_STATE", "observability/vercel_quota_state.json"))
API_DEPLOY_SKIP_PARTS = {"archive", ".git"}
_cycle_deploy_done = False


def deploy_cooldown_status() -> Dict[str, Any]:
    """Whether Vercel deploy is blocked by cooldown."""
    if not VERCEL_DEPLOY:
        return {"active": True, "reason": "VERCEL_DEPLOY disabled"}
    if not LAST_DEPLOY_FILE.exists():
        return {"active": False}
    try:
        last = datetime.fromisoformat(LAST_DEPLOY_FILE.read_text(encoding="utf-8").strip())
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        elapsed_min = (datetime.now(timezone.utc) - last).total_seconds() / 60
        if elapsed_min < VERCEL_DEPLOY_COOLDOWN_MINUTES:
            remaining = VERCEL_DEPLOY_COOLDOWN_MINUTES - elapsed_min
            return {
                "active": True,
                "reason": f"cooldown {remaining:.0f}m remaining (last deploy {last.isoformat()})",
                "last_deploy_at": last.isoformat(),
                "remaining_minutes": round(remaining, 1),
            }
    except (ValueError, OSError):
        pass
    return {"active": False}


def _record_deploy_time() -> None:
    PUBLISHED_DIR.mkdir(parents=True, exist_ok=True)
    LAST_DEPLOY_FILE.write_text(datetime.now(timezone.utc).isoformat(), encoding="utf-8")


def reset_cycle_deploy_flag() -> None:
    global _cycle_deploy_done
    _cycle_deploy_done = False


def _html_files() -> List[Path]:
    return sorted(PUBLISHED_DIR.glob("*.html"))


def build_index_html(
    treasury_address: str = "",
    featured: Optional[Dict[str, str]] = None,
) -> Path:
    """Regenerate published/index.html listing all assets."""
    PUBLISHED_DIR.mkdir(parents=True, exist_ok=True)
    files = _html_files()
    links = "\n".join(
        f'    <li><a href="{f.name}">{f.name}</a></li>'
        for f in files
        if f.name != "index.html"
    )
    featured = featured or {}
    featured_block = ""
    if featured:
        items = "\n".join(
            f'    <li><a href="{url}">{label}</a></li>'
            for label, url in featured.items()
            if url
        )
        featured_block = f"""
  <section id="featured">
    <h2>Revenue Surfaces (highest impact)</h2>
    <ul>
{items}
    </ul>
  </section>
"""
    tip_block = ""
    if treasury_address:
        tip_block = f"""
  <section id="support">
    <h2>Support RSI-EAF (XRPL Testnet)</h2>
    <p><strong>Easy pay:</strong> send testnet XRP to treasury with <strong>Destination Tag 1</strong> (or memo <code>tip</code>).</p>
    <p><strong>Treasury:</strong> <code>{treasury_address}</code> · <strong>Tag:</strong> <code>1</code></p>
    <p><a href="https://testnet.xrpl.org/">Verify on XRPL Testnet Explorer</a></p>
    <p><a href="agent-pay.json"><strong>Agent pay endpoint (JSON)</strong></a> — one file for any agent wallet</p>
    <p><a href="tip-manifest.json">Tip manifest (JSON)</a></p>
  </section>
"""
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>RSI-EAF Published Assets</title>
  <style>body{{font-family:system-ui;max-width:720px;margin:2rem auto;padding:0 1rem}}</style>
</head>
<body>
  <h1>RSI-EAF Published Assets</h1>
  <p>Verifiable factory output — each asset anchored on XRPL testnet.</p>
{featured_block}
  <ul>
{links}
  </ul>
{tip_block}
</body>
</html>
"""
    index_path = PUBLISHED_DIR / "index.html"
    index_path.write_text(html, encoding="utf-8")
    return index_path


def _write_vercel_config() -> None:
    config_path = PUBLISHED_DIR / "vercel.json"
    if not config_path.exists():
        config_path.write_text(
            json.dumps({"cleanUrls": True, "trailingSlash": False}, indent=2),
            encoding="utf-8",
        )


def factory_deploy_hook_url() -> str:
    return os.getenv("FACTORY_PUBLISH_DEPLOY_HOOK_URL", "").strip()


def _quota_error(payload: Dict[str, Any]) -> bool:
    text = json.dumps(payload).lower()
    return "api-deployments-free-per-day" in text or "deployments-free-per-day" in text


def _load_quota_state() -> Dict[str, Any]:
    if not QUOTA_STATE_FILE.exists():
        return {}
    try:
        return json.loads(QUOTA_STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _persist_quota_state(payload: Dict[str, Any]) -> None:
    QUOTA_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    QUOTA_STATE_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def record_quota_exhaustion(source: str, detail: str = "") -> Dict[str, Any]:
    """Remember daily deploy quota exhaustion so we skip CLI until reset."""
    state = {
        "schema": "rsi_eaf_vercel_quota_v1",
        "exhausted": True,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "detail_tail": (detail or "")[-500:],
        "retry_after_hours": 24,
    }
    _persist_quota_state(state)
    return state


def quota_exhausted_status() -> Dict[str, Any]:
    state = _load_quota_state()
    if not state.get("exhausted"):
        return {"active": False}
    try:
        recorded = datetime.fromisoformat(str(state.get("recorded_at", "")).replace("Z", "+00:00"))
        if recorded.tzinfo is None:
            recorded = recorded.replace(tzinfo=timezone.utc)
        elapsed_h = (datetime.now(timezone.utc) - recorded).total_seconds() / 3600
        retry_h = float(state.get("retry_after_hours") or 24)
        if elapsed_h >= retry_h:
            return {"active": False, "expired": True}
        return {
            "active": True,
            "reason": f"vercel daily quota exhausted ({retry_h - elapsed_h:.1f}h until retry)",
            "recorded_at": state.get("recorded_at"),
            "source": state.get("source"),
        }
    except (ValueError, TypeError):
        return {"active": False}


def trigger_factory_deploy_hook(*, force: bool = False, reason: str = "") -> Dict[str, Any]:
    """POST factory publish deploy hook (non-git projects may still no-op)."""
    hook = factory_deploy_hook_url()
    if not hook:
        return {"success": False, "skipped": True, "reason": "no_factory_deploy_hook_url"}
    try:
        response = httpx.post(hook, timeout=90.0)
        body = (response.text or "")[:300]
        ok = response.status_code in {200, 201, 202}
        return {
            "success": ok,
            "skipped": False,
            "method": "deploy_hook",
            "status_code": response.status_code,
            "body_preview": body,
            "trigger_reason": reason or None,
            "force": force,
        }
    except httpx.HTTPError as exc:
        return {"success": False, "skipped": False, "method": "deploy_hook", "error": str(exc)}


def _published_files_for_api(published_dir: Path) -> List[Path]:
    files: List[Path] = []
    for path in sorted(published_dir.rglob("*")):
        if not path.is_file():
            continue
        if any(part in API_DEPLOY_SKIP_PARTS for part in path.parts):
            continue
        if path.name == ".last_vercel_deploy":
            continue
        files.append(path)
    return files


def _vercel_token() -> str:
    token = (VERCEL_TOKEN or os.getenv("VERCEL_TOKEN") or "").strip()
    if token:
        return token
    try:
        from dotenv import load_dotenv

        load_dotenv()
        return (os.getenv("VERCEL_TOKEN") or "").strip()
    except ImportError:
        return ""


def deploy_via_vercel_api(
    published_dir: Optional[Path] = None,
    *,
    cycle_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Upload published/ via Vercel REST API when CLI daily quota is exhausted."""
    published_dir = published_dir or PUBLISHED_DIR
    token = _vercel_token()
    project_id = FACTORY_VERCEL_PROJECT_ID
    if not token or not project_id:
        return {
            "success": False,
            "skipped": True,
            "method": "vercel_api_files",
            "reason": "missing_vercel_token_or_project_id",
        }

    headers = {"Authorization": f"Bearer {token}"}
    files_meta: List[Dict[str, Any]] = []
    for path in _published_files_for_api(published_dir):
        data = path.read_bytes()
        digest = hashlib.sha1(data).hexdigest()
        rel = path.relative_to(published_dir).as_posix()
        try:
            up = httpx.post(
                f"https://api.vercel.com/v2/files?size={len(data)}",
                headers={
                    **headers,
                    "Content-Type": "application/octet-stream",
                    "x-vercel-digest": digest,
                },
                content=data,
                timeout=120.0,
            )
        except httpx.HTTPError as exc:
            return {"success": False, "method": "vercel_api_files", "error": str(exc)}
        if up.status_code not in {200, 201}:
            return {
                "success": False,
                "method": "vercel_api_files",
                "error": f"upload_failed:{rel}",
                "status_code": up.status_code,
                "body": (up.text or "")[:200],
            }
        files_meta.append({"file": rel, "sha": digest, "size": len(data)})

    payload: Dict[str, Any] = {
        "name": "published",
        "project": project_id,
        "target": "production",
        "files": files_meta,
        "projectSettings": {"framework": None},
        "meta": {"deployMethod": "vercel_api_files"},
    }
    if cycle_id is not None:
        payload["meta"]["factoryCycle"] = str(cycle_id)

    params: Dict[str, str] = {"forceNew": "1"}
    if FACTORY_VERCEL_TEAM_ID:
        params["teamId"] = FACTORY_VERCEL_TEAM_ID

    try:
        response = httpx.post(
            "https://api.vercel.com/v13/deployments",
            headers={**headers, "Content-Type": "application/json"},
            params=params,
            json=payload,
            timeout=300.0,
        )
        data = response.json() if response.content else {}
        ok = response.status_code in {200, 201}
        err = data.get("error") or {}
        result: Dict[str, Any] = {
            "success": ok,
            "method": "vercel_api_files",
            "status_code": response.status_code,
            "deployment_id": data.get("id"),
            "deploy_url": f"https://{data['url']}" if data.get("url") else FACTORY_PUBLIC_BASE_URL,
            "file_count": len(files_meta),
        }
        if err:
            result["error_code"] = err.get("code")
            result["error"] = err.get("message")
            if _quota_error(err):
                result["quota_exhausted"] = True
                record_quota_exhaustion("vercel_api_files", json.dumps(err))
        if ok and data.get("id"):
            deadline = time.time() + int(os.getenv("VERCEL_API_DEPLOY_WAIT_SEC", "180"))
            while time.time() < deadline:
                poll = httpx.get(
                    f"https://api.vercel.com/v13/deployments/{data['id']}",
                    headers=headers,
                    params={"teamId": FACTORY_VERCEL_TEAM_ID} if FACTORY_VERCEL_TEAM_ID else None,
                    timeout=30.0,
                )
                state = (poll.json() if poll.content else {}).get("readyState")
                if state in {"READY", "ERROR", "CANCELED"}:
                    result["ready_state"] = state
                    break
                time.sleep(5)
        return result
    except httpx.HTTPError as exc:
        return {"success": False, "method": "vercel_api_files", "error": str(exc)}


def _deploy_via_vercel_cli(
    published_dir: Path,
    *,
    prune_meta: Dict[str, Any],
) -> Dict[str, Any]:
    vercel_bin = shutil.which("vercel")
    if not vercel_bin:
        return {"success": False, "skipped": True, "reason": "vercel CLI not found"}

    cmd = [vercel_bin, "--yes", "--prod"]
    token = _vercel_token()
    if token:
        cmd.extend(["--token", token])

    env = os.environ.copy()
    if token:
        env["VERCEL_TOKEN"] = token

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=180,
            cwd=str(published_dir.resolve()),
            check=False,
            shell=os.name == "nt",
            env=env,
        )
        output = (result.stdout or "") + (result.stderr or "")
        url = None
        for line in output.splitlines():
            line = line.strip()
            if line.startswith("Aliased:"):
                url = line.split("Aliased:", 1)[1].strip().split()[0].rstrip("/")
                break
            if line.startswith("Production:"):
                url = line.split("Production:", 1)[1].strip().split()[0].rstrip("/")
        if not url:
            for line in output.splitlines():
                line = line.strip()
                if line.startswith("https://"):
                    url = line.rstrip("/")
        deploy_ok = result.returncode == 0
        payload = {
            "success": deploy_ok,
            "method": "vercel_cli",
            "deploy_url": url or FACTORY_PUBLIC_BASE_URL or None,
            "cli_output_tail": output[-500:],
            "prune": prune_meta,
        }
        if not deploy_ok and _quota_error({"output": output}):
            payload["quota_exhausted"] = True
            record_quota_exhaustion("vercel_cli", output)
        return payload
    except (subprocess.TimeoutExpired, OSError) as exc:
        return {"success": False, "method": "vercel_cli", "error": str(exc)}


def deploy_to_vercel(
    published_dir: Optional[Path] = None,
    force: bool = False,
    *,
    cycle_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Deploy published site: API files (quota workaround) → hook → CLI."""
    global _cycle_deploy_done
    published_dir = published_dir or PUBLISHED_DIR
    _write_vercel_config()

    try:
        from tools.publish_hygiene import prune_published_for_deploy

        # Always pass cycle_id so this cycle's HTML is never truncated away before gates.
        prune_meta = prune_published_for_deploy(cycle_id=cycle_id)
    except Exception:
        prune_meta = {"skipped": True}

    if not VERCEL_DEPLOY:
        return {"success": False, "skipped": True, "reason": "VERCEL_DEPLOY disabled"}

    cooldown = deploy_cooldown_status()
    if cooldown.get("active") and not force:
        return {"success": False, "skipped": True, "reason": cooldown.get("reason")}

    if _cycle_deploy_done and not force:
        return {
            "success": False,
            "skipped": True,
            "reason": "batch_deploy_already_ran_this_cycle",
            "deploy_url": FACTORY_PUBLIC_BASE_URL or None,
        }

    quota = quota_exhausted_status()
    prefer_api = os.getenv("VERCEL_DEPLOY_PREFER_API", "true").lower() in {"1", "true", "yes"}
    attempts: List[Dict[str, Any]] = []
    api_tried = False

    def _finish(result: Dict[str, Any], *, record: bool = True) -> Dict[str, Any]:
        """Attach attempt history without circular self-reference (json.dumps safe)."""
        global _cycle_deploy_done
        if record:
            _record_deploy_time()
            _cycle_deploy_done = True
        # Never nest `result` inside its own attempts list.
        history = [{k: v for k, v in a.items() if k != "attempts"} for a in attempts]
        out = {k: v for k, v in result.items() if k != "attempts"}
        out["attempts"] = history
        if not out.get("deploy_url"):
            out["deploy_url"] = FACTORY_PUBLIC_BASE_URL or None
        return out

    if quota.get("active") or prefer_api:
        api_result = deploy_via_vercel_api(published_dir, cycle_id=cycle_id)
        api_tried = True
        attempts.append(api_result)
        if api_result.get("success"):
            return _finish(api_result)

    hook_result = trigger_factory_deploy_hook(force=force, reason="factory_publish")
    attempts.append(hook_result)
    if hook_result.get("success"):
        return _finish(hook_result)

    if not quota.get("active"):
        cli_result = _deploy_via_vercel_cli(published_dir, prune_meta=prune_meta)
        attempts.append(cli_result)
        if cli_result.get("success"):
            return _finish(cli_result)
        if cli_result.get("quota_exhausted") and not api_tried:
            retry_api = deploy_via_vercel_api(published_dir, cycle_id=cycle_id)
            attempts.append(retry_api)
            if retry_api.get("success"):
                return _finish(retry_api)

    last = attempts[-1] if attempts else {"success": False, "reason": "no_deploy_method"}
    return _finish(last, record=False)


def resolve_live_url(relative_path: str, deploy_result: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """Build a queryable live URL for a published asset."""
    base = None
    if deploy_result and deploy_result.get("deploy_url"):
        base = deploy_result["deploy_url"].rstrip("/")
    elif FACTORY_PUBLIC_BASE_URL:
        base = FACTORY_PUBLIC_BASE_URL
    if not base:
        return None
    name = Path(relative_path).name
    return f"{base}/{name}"


def verify_live_url(url: str, timeout: float = 10.0) -> bool:
    try:
        response = httpx.get(url, timeout=timeout, follow_redirects=True)
        return response.status_code == 200
    except httpx.HTTPError:
        return False


def _skip_deploy_requested(skip_deploy: Optional[bool]) -> bool:
    if skip_deploy is not None:
        return skip_deploy
    return os.getenv("SKIP_VERCEL_DEPLOY", "false").lower() in {"1", "true", "yes"}


def publish_asset(
    published_path: Path,
    treasury_address: str = "",
    skip_deploy: Optional[bool] = None,
) -> Dict[str, Any]:
    """Index, optionally deploy, and resolve live URL for an asset."""
    build_index_html(treasury_address=treasury_address)
    deploy_result = (
        {"success": False, "skipped": True, "reason": "skip_deploy flag"}
        if _skip_deploy_requested(skip_deploy)
        else deploy_to_vercel()
    )
    rel = published_path.as_posix()
    live_url = resolve_live_url(published_path.name, deploy_result)

    result = {
        "published_path": str(published_path),
        "index_path": str(PUBLISHED_DIR / "index.html"),
        "deploy": deploy_result,
        "live_url": live_url,
        "live_verified": verify_live_url(live_url) if live_url else False,
    }
    return result