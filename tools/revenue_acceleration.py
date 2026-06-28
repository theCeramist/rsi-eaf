"""
Revenue acceleration — treasury-visible surfaces + outreach artifacts.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from observability.payment_intent import TIP_TAG, TIP_USD, simple_payment_instructions

DOCS_DIR = Path("docs")
PUBLISHED_DIR = Path(os.getenv("PUBLISHED_DIR", "published"))
FACTORY_PUBLIC_BASE_URL = os.getenv("FACTORY_PUBLIC_BASE_URL", "https://published-zeta.vercel.app").rstrip("/")


def write_outreach_bundle(
    cycle_id: int,
    treasury_address: str,
    featured: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Agent/human-readable outreach bundle promoting Destination Tag 1 payments."""
    from tools.distribution_tools import canonical_tip_url

    featured = featured or {}
    tip_url = canonical_tip_url(cycle_id) or featured.get("tip_page") or f"{FACTORY_PUBLIC_BASE_URL}/"
    instructions = simple_payment_instructions(cycle_id, treasury_address)

    payload = {
        "schema": "rsi_eaf_outreach_v1",
        "cycle_id": cycle_id,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "treasury_address": treasury_address,
        "destination_tag": TIP_TAG,
        "credited_usd": TIP_USD,
        "tip_page": tip_url,
        "briefing_page": featured.get("briefing_page"),
        "tip_manifest": featured.get("tip_manifest") or f"{FACTORY_PUBLIC_BASE_URL}/tip-manifest.json",
        "payment_steps": instructions["easiest"],
        "share_text": (
            f"Support RSI-EAF on XRPL testnet: send XRP to {treasury_address} "
            f"with Destination Tag {TIP_TAG} (${TIP_USD:.0f} verified tip). {tip_url}"
        ),
        "explorer": "https://testnet.xrpl.org/",
    }

    PUBLISHED_DIR.mkdir(parents=True, exist_ok=True)
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    json_path = PUBLISHED_DIR / f"outreach-cycle-{cycle_id}.json"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    md_path = DOCS_DIR / "OUTREACH.md"
    md_path.write_text(
        f"""# RSI-EAF Outreach (Cycle {cycle_id})

Updated: {payload['updated_at']}

## Easiest payment path

1. Send testnet XRP to `{treasury_address}`
2. Set **Destination Tag `{TIP_TAG}`**
3. Verified ${TIP_USD:.0f} tip ingested next cycle

**Tip page:** {tip_url}

## Share

```
{payload['share_text']}
```

## Agent JSON

`published/outreach-cycle-{cycle_id}.json`
""",
        encoding="utf-8",
    )

    return {
        "outreach_json": str(json_path),
        "outreach_md": str(md_path),
        "tip_url": tip_url,
        "payload": payload,
    }


def accelerate_treasury_surfaces(
    cycle_id: int,
    treasury_address: str,
    featured: Optional[Dict[str, str]] = None,
    factory_state: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Promote treasury payment surfaces: outreach bundle, index refresh, manifest, deploy.
    """
    from tools.distribution_tools import featured_links_for_index, write_tip_manifest
    from tools.publish_tools import build_index_html, deploy_to_vercel, verify_live_url

    featured = featured or featured_links_for_index(cycle_id)
    outreach = write_outreach_bundle(cycle_id, treasury_address, featured)

    write_tip_manifest(
        treasury_address=treasury_address,
        cycle_id=cycle_id,
        live_tip_url=outreach["tip_url"],
    )
    build_index_html(treasury_address=treasury_address, featured=featured)
    deploy = deploy_to_vercel()

    tip_live = verify_live_url(outreach["tip_url"]) if outreach.get("tip_url") else False
    if factory_state is not None:
        factory_state.set_github_distribution({
            "cycle_id": cycle_id,
            "canonical_tip_url": outreach["tip_url"],
            "outreach_json": outreach["outreach_json"],
            "vercel_index": f"{FACTORY_PUBLIC_BASE_URL}/",
        })

    return {
        "action": "accelerate_treasury_surfaces",
        "implemented": tip_live or outreach.get("outreach_json"),
        "outreach": outreach,
        "deploy": deploy,
        "tip_live": tip_live,
        "cycle_id": cycle_id,
    }
