"""
Agent Service Marketplace — agent-readable catalog of payable factory capabilities.
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from observability.payment_intent import SERVICE_TAG, SERVICE_USD
from revenue_engines.base_engine import RevenueEngine, publish_and_anchor, resolve_treasury

SOURCE = "agent_marketplace_v1"
PUBLISHED_DIR = os.getenv("PUBLISHED_DIR", "published")
FACTORY_PUBLIC_BASE_URL = os.getenv("FACTORY_PUBLIC_BASE_URL", "").rstrip("/")


def _service_catalog(cycle_id: int, treasury: str) -> Dict[str, Any]:
    base = FACTORY_PUBLIC_BASE_URL or "https://published-zeta.vercel.app"
    services: List[Dict[str, Any]] = [
        {
            "id": "treasury_tip_verify",
            "price_usd": 1.0,
            "payment": {"destination_tag": 1, "memo": "tip"},
            "deliverable": f"{base}/tip-manifest.json",
        },
        {
            "id": "xrpl_briefing_unlock",
            "price_usd": 2.0,
            "payment": {"destination_tag": 2, "memo": "briefing"},
            "deliverable": f"{base}/briefing-cycle-{cycle_id}.html",
        },
        {
            "id": "micro_tool_unlock",
            "price_usd": 3.0,
            "payment": {"destination_tag": 3, "memo": "tool"},
            "deliverable": f"{base}/micro-tool-cycle-{cycle_id}",
        },
        {
            "id": "agent_service_bundle",
            "price_usd": SERVICE_USD,
            "payment": {"destination_tag": SERVICE_TAG, "memo": "service"},
            "deliverable": "cycle_trace_summary + nexus wave metadata",
        },
    ]
    return {
        "schema": "rsi_eaf_service_catalog_v1",
        "cycle_id": cycle_id,
        "treasury_address": treasury,
        "network": "xrpl_testnet",
        "services": services,
        "acp_ready": True,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


class AgentMarketplace(RevenueEngine):
    source = SOURCE

    def __init__(self, published_dir: str = PUBLISHED_DIR):
        self.published_dir = Path(published_dir)
        self.published_dir.mkdir(parents=True, exist_ok=True)

    def _build_html(self, cycle_id: int, treasury: str, catalog: Dict[str, Any]) -> str:
        rows = ""
        for svc in catalog["services"]:
            pay = svc["payment"]
            rows += (
                f"<tr><td>{svc['id']}</td><td>${svc['price_usd']:.2f}</td>"
                f"<td>Tag {pay.get('destination_tag')} / memo '{pay.get('memo')}'</td>"
                f"<td><code>{svc['deliverable']}</code></td></tr>"
            )
        return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>Agent Service Catalog — Cycle {cycle_id}</title>
<style>body{{font-family:system-ui,sans-serif;max-width:800px;margin:2rem auto;padding:0 1rem}}
table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #ccc;padding:.5rem;text-align:left}}</style>
</head>
<body>
<h1>RSI-EAF Agent Service Marketplace</h1>
<p>Payable capabilities for agents (ACP / JSON manifest). Treasury: <code>{treasury}</code></p>
<table><thead><tr><th>Service</th><th>Price</th><th>Pay</th><th>Deliverable</th></tr></thead>
<tbody>{rows}</tbody></table>
<p><a href="service-catalog.json">service-catalog.json</a></p>
<footer><small>{SOURCE} · cycle {cycle_id}</small></footer>
</body></html>"""

    def run(self, cycle_id: int) -> Dict[str, Any]:
        treasury = resolve_treasury()
        catalog = _service_catalog(cycle_id, treasury)
        catalog_path = self.published_dir / "service-catalog.json"
        catalog_path.write_text(json.dumps(catalog, indent=2), encoding="utf-8")
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        html_path = self.published_dir / f"services-cycle-{cycle_id}-{timestamp}.html"
        html_path.write_text(self._build_html(cycle_id, treasury, catalog), encoding="utf-8")
        return publish_and_anchor(
            source=SOURCE,
            cycle_id=cycle_id,
            html_path=html_path,
            treasury=treasury,
            notes=f"Agent service catalog cycle-{cycle_id}",
            event_type="agent_catalog_published",
            extra_memo={
                "product_id": f"service-bundle-cycle-{cycle_id}",
                "unlock_price_usd": SERVICE_USD,
                "destination_tag": SERVICE_TAG,
            },
            extra_metadata={"catalog": catalog, "revenue_model": "agent_marketplace"},
        )