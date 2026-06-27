"""
Distribution assets — sitemaps, payment manifests, featured index surfaces.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

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
    manifest = {
        "schema": "rsi_eaf_tip_manifest_v1",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "cycle_id": cycle_id,
        "network": "xrpl_testnet",
        "treasury_address": treasury_address,
        "payment_memo_template": {
            "type": "revenue",
            "amount_usd_est": suggested_amount_usd,
            "notes": "supporter tip",
            "source": "tip_manifest",
        },
        "suggested_amounts_usd": [0.5, 1.0, 2.5, 5.0],
        "explorer": "https://testnet.xrpl.org/",
        "live_tip_page": live_tip_url,
        "verification": "Payment ingested when memo includes type=revenue and amount_usd_est > 0",
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


def featured_links_for_index(cycle_id: int) -> Dict[str, str]:
    """Resolve featured revenue surfaces for the index page."""
    links: Dict[str, str] = {}
    tip_pages = sorted(PUBLISHED_DIR.glob(f"tip-cycle-{cycle_id}-*.html"))
    briefing_pages = sorted(PUBLISHED_DIR.glob(f"briefing-cycle-{cycle_id}-*.html"))
    if tip_pages:
        name = tip_pages[-1].name
        links["tip_page"] = f"{FACTORY_PUBLIC_BASE_URL}/{name}" if FACTORY_PUBLIC_BASE_URL else name
    if briefing_pages:
        name = briefing_pages[-1].name
        links["briefing_page"] = (
            f"{FACTORY_PUBLIC_BASE_URL}/{name}" if FACTORY_PUBLIC_BASE_URL else name
        )
    if FACTORY_PUBLIC_BASE_URL:
        links["tip_manifest"] = f"{FACTORY_PUBLIC_BASE_URL}/tip-manifest.json"
    return links