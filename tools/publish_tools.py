"""
Publishing tools — deploy /published assets to a verifiable live URL.
"""

import json
import os
import shutil
import subprocess
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
LAST_DEPLOY_FILE = PUBLISHED_DIR / ".last_vercel_deploy"
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


def deploy_to_vercel(
    published_dir: Optional[Path] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """Deploy published static site via Vercel CLI when available."""
    global _cycle_deploy_done
    published_dir = published_dir or PUBLISHED_DIR
    _write_vercel_config()

    try:
        from tools.publish_hygiene import prune_published_for_deploy

        prune_meta = prune_published_for_deploy()
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

    vercel_bin = shutil.which("vercel")
    if not vercel_bin:
        return {"success": False, "skipped": True, "reason": "vercel CLI not found"}

    cmd = [vercel_bin, "--yes", "--prod"]
    if VERCEL_TOKEN:
        cmd.extend(["--token", VERCEL_TOKEN])

    env = os.environ.copy()
    if VERCEL_TOKEN:
        env["VERCEL_TOKEN"] = VERCEL_TOKEN

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
        if deploy_ok:
            _record_deploy_time()
            _cycle_deploy_done = True
        return {
            "success": deploy_ok,
            "deploy_url": url or FACTORY_PUBLIC_BASE_URL or None,
            "cli_output_tail": output[-500:],
            "prune": prune_meta,
        }
    except (subprocess.TimeoutExpired, OSError) as exc:
        return {"success": False, "error": str(exc)}


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