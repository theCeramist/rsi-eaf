"""
Publishing tools — deploy /published assets to a verifiable live URL.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

PUBLISHED_DIR = Path(os.getenv("PUBLISHED_DIR", "published"))
FACTORY_PUBLIC_BASE_URL = os.getenv("FACTORY_PUBLIC_BASE_URL", "").rstrip("/")
VERCEL_DEPLOY = os.getenv("VERCEL_DEPLOY", "true").lower() in {"1", "true", "yes"}
VERCEL_TOKEN = os.getenv("VERCEL_TOKEN")


def _html_files() -> List[Path]:
    return sorted(PUBLISHED_DIR.glob("*.html"))


def build_index_html(treasury_address: str = "") -> Path:
    """Regenerate published/index.html listing all assets."""
    PUBLISHED_DIR.mkdir(parents=True, exist_ok=True)
    files = _html_files()
    links = "\n".join(
        f'    <li><a href="{f.name}">{f.name}</a></li>'
        for f in files
        if f.name != "index.html"
    )
    tip_block = ""
    if treasury_address:
        tip_block = f"""
  <section id="support">
    <h2>Support RSI-EAF (XRPL Testnet)</h2>
    <p>Send a testnet payment to the factory treasury with this memo JSON:</p>
    <pre>{{"type":"revenue","amount_usd_est":1.0,"notes":"supporter tip"}}</pre>
    <p><strong>Treasury:</strong> <code>{treasury_address}</code></p>
    <p><a href="https://testnet.xrpl.org/">Verify on XRPL Testnet Explorer</a></p>
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


def deploy_to_vercel(published_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Deploy published static site via Vercel CLI when available."""
    published_dir = published_dir or PUBLISHED_DIR
    _write_vercel_config()

    if not VERCEL_DEPLOY:
        return {"success": False, "skipped": True, "reason": "VERCEL_DEPLOY disabled"}

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
        return {
            "success": result.returncode == 0,
            "deploy_url": url or FACTORY_PUBLIC_BASE_URL or None,
            "cli_output_tail": output[-500:],
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


def publish_asset(
    published_path: Path,
    treasury_address: str = "",
) -> Dict[str, Any]:
    """Index, optionally deploy, and resolve live URL for an asset."""
    build_index_html(treasury_address=treasury_address)
    deploy_result = deploy_to_vercel()
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