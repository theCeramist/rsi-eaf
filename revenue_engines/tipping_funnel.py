"""
Tipping Funnel — high-conversion XRPL treasury landing + agent payment manifest.
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from revenue_engines.base_engine import RevenueEngine, publish_and_anchor, resolve_treasury
from tools.distribution_tools import write_tip_manifest

SOURCE = "tipping_funnel_v1"
PUBLISHED_DIR = os.getenv("PUBLISHED_DIR", "published")
DEFAULT_TIP_USD = float(os.getenv("TIP_SUGGESTED_USD", "1.0"))


class TippingFunnel(RevenueEngine):
    source = SOURCE

    def __init__(self, published_dir: str = PUBLISHED_DIR):
        self.published_dir = Path(published_dir)
        self.published_dir.mkdir(parents=True, exist_ok=True)

    def _build_html(self, cycle_id: int, treasury: str, memo_template: Dict[str, Any]) -> str:
        memo_json = json.dumps(memo_template, separators=(",", ":"))
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="description" content="Support RSI-EAF via verifiable XRPL testnet payment">
  <meta property="og:title" content="Support RSI-EAF — Cycle {cycle_id}">
  <title>Support RSI-EAF — Cycle {cycle_id}</title>
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 640px; margin: 2rem auto; padding: 0 1rem; line-height: 1.5; }}
    .cta {{ background: #0a7; color: #fff; padding: 1rem; border-radius: 8px; margin: 1.5rem 0; }}
    code, pre {{ background: #f4f4f4; padding: 0.2rem 0.4rem; border-radius: 4px; font-size: 0.9rem; }}
    pre {{ padding: 1rem; overflow-x: auto; }}
    button {{ cursor: pointer; padding: 0.5rem 1rem; margin-top: 0.5rem; }}
  </style>
</head>
<body>
  <h1>Fund Autonomous Factory Research</h1>
  <p>RSI-EAF publishes verifiable assets anchored on XRPL. Your testnet tip becomes
     <strong>verified revenue</strong> when the treasury receives a payment with the memo below.</p>

  <div class="cta">
    <h2>XRPL Testnet Treasury</h2>
    <p><code id="treasury">{treasury}</code></p>
    <button type="button" onclick="navigator.clipboard.writeText(document.getElementById('treasury').textContent)">Copy address</button>
  </div>

  <h3>Payment memo (required for verified revenue)</h3>
  <pre id="memo">{memo_json}</pre>
  <button type="button" onclick="navigator.clipboard.writeText(document.getElementById('memo').textContent)">Copy memo JSON</button>

  <p>Suggested tip: <strong>${DEFAULT_TIP_USD:.2f}</strong> (set <code>amount_usd_est</code> in memo).</p>
  <p><a href="https://testnet.xrpl.org/">Verify payments on XRPL Testnet Explorer</a></p>
  <p><a href="tip-manifest.json">Agent payment manifest (JSON)</a></p>
  <footer><small>{SOURCE} · cycle {cycle_id}</small></footer>
</body>
</html>
"""

    def run(self, cycle_id: int) -> Dict[str, Any]:
        treasury = resolve_treasury()
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        slug = f"tip-cycle-{cycle_id}-{timestamp}"
        memo_template = {
            "type": "revenue",
            "amount_usd_est": DEFAULT_TIP_USD,
            "notes": f"supporter tip cycle {cycle_id}",
            "source": SOURCE,
            "cycle_id": cycle_id,
        }

        html_path = self.published_dir / f"{slug}.html"
        html_path.write_text(self._build_html(cycle_id, treasury, memo_template), encoding="utf-8")

        result = publish_and_anchor(
            source=SOURCE,
            cycle_id=cycle_id,
            html_path=html_path,
            treasury=treasury,
            notes=f"Tipping funnel {slug}",
            event_type="tip_funnel_published",
            extra_memo={"funnel": "treasury_tip", "suggested_usd": DEFAULT_TIP_USD},
            extra_metadata={"memo_template": memo_template, "funnel_type": "treasury_tip"},
        )

        manifest_path = write_tip_manifest(
            treasury_address=treasury,
            cycle_id=cycle_id,
            suggested_amount_usd=DEFAULT_TIP_USD,
            live_tip_url=result.get("live_url"),
        )
        result["tip_manifest"] = str(manifest_path)
        return result