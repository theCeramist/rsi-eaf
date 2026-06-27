"""
Paid Briefing — XRPL intelligence micro-product with gated unlock via treasury payment.
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from observability.revenue_ingest import _extract_payment_fields
from revenue_engines.base_engine import RevenueEngine, publish_and_anchor, resolve_treasury
from tools.xrpl_research import (
    format_briefing_full,
    format_briefing_teaser,
    gather_factory_intel,
)
from tools.xrpl_tools import FACTORY_XRPL_ADDRESS, query_recent_transactions

SOURCE = "paid_briefing_v1"
PUBLISHED_DIR = os.getenv("PUBLISHED_DIR", "published")
UNLOCK_PRICE_USD = float(os.getenv("BRIEFING_UNLOCK_USD", "2.0"))
INGEST_LIMIT = int(os.getenv("REVENUE_INGEST_TX_LIMIT", "20"))


def _product_id(cycle_id: int) -> str:
    return f"briefing-cycle-{cycle_id}"


def _find_unlocked_products(treasury: str) -> Set[str]:
    """Scan treasury for external payments with product_id in revenue memos."""
    internal = {a for a in (FACTORY_XRPL_ADDRESS, treasury) if a}
    unlocked: Set[str] = set()
    for entry in query_recent_transactions(treasury, limit=INGEST_LIMIT):
        payment = _extract_payment_fields(entry)
        if not payment or payment.get("from") in internal:
            continue
        for memo in payment.get("memos") or []:
            if memo.get("type") == "revenue" and memo.get("product_id"):
                unlocked.add(str(memo["product_id"]))
    return unlocked


class PaidBriefing(RevenueEngine):
    source = SOURCE

    def __init__(self, published_dir: str = PUBLISHED_DIR):
        self.published_dir = Path(published_dir)
        self.published_dir.mkdir(parents=True, exist_ok=True)

    def _build_html(
        self,
        cycle_id: int,
        treasury: str,
        intel: Dict[str, Any],
        unlocked: bool,
        product_id: str,
    ) -> str:
        memo_unlock = json.dumps(
            {
                "type": "revenue",
                "amount_usd_est": UNLOCK_PRICE_USD,
                "product_id": product_id,
                "notes": f"unlock {product_id}",
                "source": SOURCE,
            },
            separators=(",", ":"),
        )
        body = format_briefing_full(intel) if unlocked else format_briefing_teaser(intel)
        gate = ""
        if not unlocked:
            gate = f"""
  <section id="unlock" style="border:2px dashed #888;padding:1rem;margin:1.5rem 0">
    <h2>Unlock Full Briefing — ${UNLOCK_PRICE_USD:.2f}</h2>
    <p>Send XRPL testnet payment to <code>{treasury}</code> with memo:</p>
    <pre>{memo_unlock}</pre>
    <p>Re-run factory cycle after payment to publish unlocked report automatically.</p>
  </section>
"""
        status = "UNLOCKED" if unlocked else "PREVIEW"
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>XRPL Factory Briefing — Cycle {cycle_id} [{status}]</title>
  <style>body{{font-family:system-ui;max-width:720px;margin:2rem auto;padding:0 1rem}}pre{{white-space:pre-wrap;background:#f8f8f8;padding:1rem}}</style>
</head>
<body>
  <h1>XRPL Factory Intelligence Briefing</h1>
  <p><em>Cycle {cycle_id} · {status} · {SOURCE}</em></p>
  <pre>{body}</pre>
{gate}
</body>
</html>
"""

    def run(self, cycle_id: int) -> Dict[str, Any]:
        treasury = resolve_treasury()
        product_id = _product_id(cycle_id)
        unlocked_products = _find_unlocked_products(treasury)
        unlocked = product_id in unlocked_products

        intel = gather_factory_intel(cycle_id)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        slug = f"briefing-cycle-{cycle_id}-{timestamp}"
        html_path = self.published_dir / f"{slug}.html"
        html_path.write_text(
            self._build_html(cycle_id, treasury, intel, unlocked, product_id),
            encoding="utf-8",
        )

        result = publish_and_anchor(
            source=SOURCE,
            cycle_id=cycle_id,
            html_path=html_path,
            treasury=treasury,
            notes=f"Paid briefing {slug} ({'unlocked' if unlocked else 'preview'})",
            event_type="briefing_published",
            extra_memo={
                "product_id": product_id,
                "unlock_price_usd": UNLOCK_PRICE_USD,
                "unlocked": unlocked,
            },
            extra_metadata={
                "product_id": product_id,
                "unlock_price_usd": UNLOCK_PRICE_USD,
                "unlocked": unlocked,
                "intel_snapshot": intel,
            },
        )
        result["product_id"] = product_id
        result["unlocked"] = unlocked
        return result