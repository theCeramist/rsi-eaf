"""
Distribution assets — sitemaps, payment manifests, featured index surfaces.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from observability.payment_intent import (
    BRIEFING_TAG,
    BRIEFING_USD,
    TIP_TAG,
    TIP_USD,
    simple_payment_instructions,
)

PUBLISHED_DIR = Path(os.getenv("PUBLISHED_DIR", "published"))
FACTORY_PUBLIC_BASE_URL = os.getenv("FACTORY_PUBLIC_BASE_URL", "").rstrip("/")


def write_tip_manifest(
    treasury_address: str,
    cycle_id: int,
    suggested_amount_usd: float = 1.0,
    live_tip_url: Optional[str] = None,
) -> Path:
    """Agent-readable payment request for XRPL treasury tipping."""
    PUBLISHED_DIR.mkdir(parents=True, exist_ok=True)
    instructions = simple_payment_instructions(cycle_id, treasury_address)
    manifest = {
        "schema": "rsi_eaf_tip_manifest_v2",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "cycle_id": cycle_id,
        "network": "xrpl_testnet",
        "treasury_address": treasury_address,
        "human_easy_path": instructions["easiest"],
        "destination_tags": {
            "tip": {"tag": TIP_TAG, "credited_usd": TIP_USD},
            "briefing_unlock": {
                "tag": BRIEFING_TAG,
                "credited_usd": BRIEFING_USD,
                "product_id": instructions["briefing_unlock"]["product_id"],
            },
        },
        "plain_memo_aliases": instructions["alternatives"],
        "payment_memo_template": {
            "type": "revenue",
            "amount_usd_est": suggested_amount_usd,
            "notes": "supporter tip",
            "source": "tip_manifest",
        },
        "explorer": "https://testnet.xrpl.org/",
        "live_tip_page": live_tip_url,
        "verification": "Tag 1, memo 'tip', or flat external payment → verified tip",
    }
    path = PUBLISHED_DIR / "tip-manifest.json"
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return path


def write_sitemap(live_urls: Optional[List[str]] = None) -> Path:
    PUBLISHED_DIR.mkdir(parents=True, exist_ok=True)
    urls = live_urls or []
    if not urls and FACTORY_PUBLIC_BASE_URL:
        for html in sorted(PUBLISHED_DIR.glob("*.html")):
            if html.name != "index.html":
                urls.append(f"{FACTORY_PUBLIC_BASE_URL}/{html.name}")
        if (PUBLISHED_DIR / "tip-manifest.json").exists():
            urls.append(f"{FACTORY_PUBLIC_BASE_URL}/tip-manifest.json")

    entries = "\n".join(f"  <url><loc>{u}</loc></url>" for u in urls)
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{entries}
</urlset>
"""
    path = PUBLISHED_DIR / "sitemap.xml"
    path.write_text(xml, encoding="utf-8")
    return path


def _tip_cycle_number(path: Path) -> int:
    import re

    match = re.search(r"tip-cycle-(\d+)", path.name)
    return int(match.group(1)) if match else 0


def canonical_tip_url(cycle_id: Optional[int] = None) -> Optional[str]:
    """
    Single promoted tip URL — prefers current cycle, then highest cycle number reachable.
    """
    override = os.getenv("CANONICAL_TIP_URL", "").strip()
    if override:
        return override.rstrip("/")

    if not FACTORY_PUBLIC_BASE_URL:
        return None

    from tools.publish_tools import verify_live_url

    base = FACTORY_PUBLIC_BASE_URL.rstrip("/")
    prefer_current = os.getenv("PREFER_CURRENT_CYCLE_TIP", "true").lower() in {"1", "true", "yes"}

    if cycle_id is not None and prefer_current:
        current_pages = sorted(PUBLISHED_DIR.glob(f"tip-cycle-{cycle_id}-*.html"), reverse=True)
        for path in current_pages:
            url = f"{base}/{path.name}"
            if verify_live_url(url):
                return url
            return url

    candidates = sorted(
        PUBLISHED_DIR.glob("tip-cycle-*.html"),
        key=_tip_cycle_number,
        reverse=True,
    )
    for path in candidates:
        url = f"{base}/{path.name}"
        if verify_live_url(url):
            return url

    manifest = f"{base}/tip-manifest.json"
    if verify_live_url(manifest):
        return manifest
    if verify_live_url(f"{base}/"):
        return f"{base}/"
    return None


def featured_links_for_index(cycle_id: int) -> Dict[str, str]:
    """Resolve featured revenue surfaces for the index page."""
    links: Dict[str, str] = {}
    canonical = canonical_tip_url(cycle_id)
    if canonical:
        links["tip_page"] = canonical
        links["canonical_tip_page"] = canonical
    else:
        tip_pages = sorted(PUBLISHED_DIR.glob(f"tip-cycle-{cycle_id}-*.html"))
        if tip_pages:
            name = tip_pages[-1].name
            links["tip_page"] = f"{FACTORY_PUBLIC_BASE_URL}/{name}" if FACTORY_PUBLIC_BASE_URL else name

    briefing_pages = sorted(PUBLISHED_DIR.glob(f"briefing-cycle-{cycle_id}-*.html"))
    if briefing_pages:
        name = briefing_pages[-1].name
        links["briefing_page"] = (
            f"{FACTORY_PUBLIC_BASE_URL}/{name}" if FACTORY_PUBLIC_BASE_URL else name
        )
    if FACTORY_PUBLIC_BASE_URL:
        links["tip_manifest"] = f"{FACTORY_PUBLIC_BASE_URL}/tip-manifest.json"
        links["service_catalog"] = f"{FACTORY_PUBLIC_BASE_URL}/service-catalog.json"
    mythos_pages = sorted(PUBLISHED_DIR.glob(f"mythos-cycle-{cycle_id}-*.html"))
    if mythos_pages:
        name = mythos_pages[-1].name
        links["mythos_page"] = f"{FACTORY_PUBLIC_BASE_URL}/{name}" if FACTORY_PUBLIC_BASE_URL else name
    micro_pages = sorted(PUBLISHED_DIR.glob(f"micro-tool-cycle-{cycle_id}-*.html"))
    if micro_pages:
        name = micro_pages[-1].name
        links["micro_tool_page"] = f"{FACTORY_PUBLIC_BASE_URL}/{name}" if FACTORY_PUBLIC_BASE_URL else name
    return links