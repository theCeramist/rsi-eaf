"""
Tipping Funnel — one-field XRPL payments via Destination Tag (no JSON memo).
"""

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from observability.payment_intent import (
    BRIEFING_TAG,
    BRIEFING_USD,
    TIP_TAG,
    TIP_USD,
    simple_payment_instructions,
)
from revenue_engines.base_engine import RevenueEngine, publish_and_anchor, resolve_treasury
from tools.distribution_tools import write_tip_manifest

SOURCE = "tipping_funnel_v1"
PUBLISHED_DIR = os.getenv("PUBLISHED_DIR", "published")


class TippingFunnel(RevenueEngine):
    source = SOURCE

    def __init__(self, published_dir: str = PUBLISHED_DIR):
        self.published_dir = Path(published_dir)
        self.published_dir.mkdir(parents=True, exist_ok=True)

    def _build_html(self, cycle_id: int, treasury: str, instructions: Dict[str, Any]) -> str:
        tag = instructions["easiest"]["destination_tag"]
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="description" content="Support RSI-EAF — send XRP with Destination Tag {tag}">
  <title>Support RSI-EAF — 2 fields only</title>
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 520px; margin: 2rem auto; padding: 0 1rem; }}
    .step {{ border: 2px solid #0a7; border-radius: 12px; padding: 1.25rem; margin: 1rem 0; }}
    .tag {{ font-size: 3rem; font-weight: 800; color: #0a7; margin: 0; }}
    code {{ background: #f0f0f0; padding: 0.2rem 0.5rem; border-radius: 4px; word-break: break-all; }}
    button {{ cursor: pointer; padding: 0.6rem 1.2rem; font-size: 1rem; margin: 0.5rem 0.5rem 0 0; }}
    .muted {{ color: #555; font-size: 0.9rem; }}
  </style>
</head>
<body>
  <h1>Support the factory</h1>
  <p><strong>Two fields.</strong> No JSON. No long memo.</p>

  <div class="step">
    <p><strong>1. Address</strong> (XRPL testnet)</p>
    <p><code id="treasury">{treasury}</code></p>
    <button type="button" onclick="navigator.clipboard.writeText('{treasury}')">Copy address</button>
  </div>

  <div class="step">
    <p><strong>2. Destination Tag</strong></p>
    <p class="tag" id="tag">{tag}</p>
    <button type="button" onclick="navigator.clipboard.writeText('{tag}')">Copy tag</button>
    <p class="muted">Counts as ${TIP_USD:.0f} verified tip. Send any testnet XRP amount.</p>
  </div>

  <p class="muted">Optional: type <code>tip</code> in the memo field instead of using a tag.<br>
     Briefing unlock (${BRIEFING_USD:.0f}): use Destination Tag <strong>{BRIEFING_TAG}</strong> or memo <code>briefing</code>.</p>
  <p><a href="https://testnet.xrpl.org/">Verify on explorer</a> · <a href="tip-manifest.json">Agent manifest</a></p>
  <footer><small>{SOURCE} · cycle {cycle_id}</small></footer>
</body>
</html>
"""

    def run(self, cycle_id: int) -> Dict[str, Any]:
        treasury = resolve_treasury()
        instructions = simple_payment_instructions(cycle_id, treasury)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        slug = f"tip-cycle-{cycle_id}-{timestamp}"

        html_path = self.published_dir / f"{slug}.html"
        html_path.write_text(self._build_html(cycle_id, treasury, instructions), encoding="utf-8")

        result = publish_and_anchor(
            source=SOURCE,
            cycle_id=cycle_id,
            html_path=html_path,
            treasury=treasury,
            notes=f"Tipping funnel {slug}",
            event_type="tip_funnel_published",
            extra_memo={"funnel": "treasury_tip", "destination_tag": TIP_TAG},
            extra_metadata={"payment_instructions": instructions, "funnel_type": "destination_tag"},
        )

        manifest_path = write_tip_manifest(
            treasury_address=treasury,
            cycle_id=cycle_id,
            live_tip_url=result.get("live_url"),
        )
        result["tip_manifest"] = str(manifest_path)
        return result