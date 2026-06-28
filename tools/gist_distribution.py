"""
Gist distribution — shareable tip manifest URLs for agent/human discovery.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx

from tools.github_client import github_headers, github_token

GIST_DESCRIPTION_PREFIX = "RSI-EAF tip manifest"


def _gist_filename(cycle_id: int) -> str:
    return f"rsi-eaf-tip-manifest-cycle-{cycle_id}.json"


def build_gist_content(cycle_id: int, featured: Dict[str, str], treasury_address: str) -> str:
    payload = {
        "cycle_id": cycle_id,
        "updated": datetime.now(timezone.utc).isoformat(),
        "treasury_address": treasury_address,
        "destination_tag_tip": 1,
        "destination_tag_briefing": 2,
        "tip_page": featured.get("tip_page"),
        "tip_manifest": featured.get("tip_manifest"),
        "briefing_page": featured.get("briefing_page"),
        "vercel_index": os.getenv("FACTORY_PUBLIC_BASE_URL", "https://published-zeta.vercel.app/"),
        "payment_memo_template": {
            "type": "revenue",
            "amount_usd_est": 1.0,
            "notes": "supporter tip",
            "source": "gist_manifest",
        },
    }
    return json.dumps(payload, indent=2)


def create_or_update_tip_gist(
    cycle_id: int,
    featured: Dict[str, str],
    treasury_address: str,
    gist_id: Optional[str] = None,
) -> Dict[str, Any]:
    token = github_token()
    if not token:
        return {"success": False, "skipped": True, "reason": "no_github_token"}

    filename = _gist_filename(cycle_id)
    content = build_gist_content(cycle_id, featured, treasury_address)
    headers = github_headers()
    payload = {
        "description": f"{GIST_DESCRIPTION_PREFIX} cycle {cycle_id}",
        "public": True,
        "files": {filename: {"content": content}},
    }

    try:
        if gist_id:
            url = f"https://api.github.com/gists/{gist_id}"
            response = httpx.patch(url, headers=headers, json=payload, timeout=60.0)
        else:
            url = "https://api.github.com/gists"
            response = httpx.post(url, headers=headers, json=payload, timeout=60.0)
        ok = response.status_code in {200, 201}
        data = response.json() if ok else {}
        return {
            "success": ok,
            "gist_id": data.get("id") or gist_id,
            "gist_url": data.get("html_url"),
            "raw_url": (data.get("files") or {}).get(filename, {}).get("raw_url"),
            "status_code": response.status_code,
        }
    except httpx.HTTPError as exc:
        return {"success": False, "error": str(exc)}


def maybe_publish_tip_gist(
    cycle_id: int,
    featured: Dict[str, str],
    treasury_address: str,
    factory_state: Optional[Any] = None,
    force: bool = False,
) -> Dict[str, Any]:
    every_n = int(os.getenv("GIST_PUBLISH_EVERY_N_CYCLES", "3"))
    if not force and cycle_id % every_n != 0:
        return {"published": False, "skipped": True, "reason": f"not due (every {every_n})"}

    gist_id = None
    if factory_state is not None and hasattr(factory_state, "get_gist_distribution"):
        gist_id = factory_state.get_gist_distribution().get("gist_id")

    result = create_or_update_tip_gist(cycle_id, featured, treasury_address, gist_id=gist_id)
    if factory_state is not None and result.get("success") and hasattr(factory_state, "set_gist_distribution"):
        factory_state.set_gist_distribution({
            "cycle_id": cycle_id,
            "gist_id": result.get("gist_id"),
            "gist_url": result.get("gist_url"),
            "raw_url": result.get("raw_url"),
        })
    return {"published": result.get("success", False), **result}