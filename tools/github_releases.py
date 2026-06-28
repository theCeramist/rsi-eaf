"""
GitHub releases — versioned briefing bundles per cycle.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

from tools.github_client import github_headers, github_token

GITHUB_OWNER = os.getenv("GITHUB_DISTRIBUTION_OWNER", "theCeramist")
GITHUB_REPO = os.getenv("GITHUB_DISTRIBUTION_REPO", "rsi-eaf")
PUBLISHED_DIR = Path(os.getenv("PUBLISHED_DIR", "published"))
RELEASE_EVERY_N = int(os.getenv("GITHUB_RELEASE_EVERY_N_CYCLES", "5"))


def create_cycle_release(
    cycle_id: int,
    *,
    briefing_path: Optional[str] = None,
    treasury_address: str = "",
    tag: Optional[str] = None,
) -> Dict[str, Any]:
    token = github_token()
    if not token:
        return {"success": False, "skipped": True, "reason": "no_github_token"}

    tag_name = tag or f"cycle-{cycle_id}"
    briefing_file = None
    if briefing_path:
        briefing_file = Path(briefing_path)
    else:
        matches = sorted(PUBLISHED_DIR.glob(f"briefing-cycle-{cycle_id}-*.html"))
        briefing_file = matches[-1] if matches else None

    body = (
        f"RSI-EAF paid briefing bundle for cycle {cycle_id}.\n\n"
        f"Unlock: XRPL testnet payment Tag 2 or memo `briefing` with "
        f"`product_id: briefing-cycle-{cycle_id}`.\n\n"
        f"Treasury: `{treasury_address}`"
    )
    payload = {
        "tag_name": tag_name,
        "name": f"RSI-EAF Cycle {cycle_id} Briefing",
        "body": body,
        "draft": False,
        "prerelease": True,
    }

    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases"
    try:
        response = httpx.post(url, headers=github_headers(), json=payload, timeout=60.0)
        ok = response.status_code == 201
        data = response.json() if ok else {}
        result: Dict[str, Any] = {
            "success": ok,
            "tag": tag_name,
            "release_id": data.get("id"),
            "html_url": data.get("html_url"),
            "status_code": response.status_code,
        }
        if ok and briefing_file and briefing_file.exists():
            upload_url = data.get("upload_url", "").split("{")[0]
            if upload_url:
                asset_resp = httpx.post(
                    f"{upload_url}?name={briefing_file.name}",
                    headers={**github_headers(), "Content-Type": "text/html"},
                    content=briefing_file.read_bytes(),
                    timeout=120.0,
                )
                result["asset_uploaded"] = asset_resp.status_code == 201
        return result
    except httpx.HTTPError as exc:
        return {"success": False, "error": str(exc)}


def maybe_create_cycle_release(
    cycle_id: int,
    treasury_address: str = "",
    factory_state: Optional[Any] = None,
    force: bool = False,
) -> Dict[str, Any]:
    if not force and cycle_id % RELEASE_EVERY_N != 0:
        return {"created": False, "skipped": True, "reason": f"every {RELEASE_EVERY_N} cycles"}
    result = create_cycle_release(cycle_id, treasury_address=treasury_address)
    if factory_state is not None and result.get("success") and hasattr(factory_state, "set_release"):
        factory_state.set_release({
            "cycle_id": cycle_id,
            "tag": result.get("tag"),
            "html_url": result.get("html_url"),
        })
    return {"created": result.get("success", False), **result}