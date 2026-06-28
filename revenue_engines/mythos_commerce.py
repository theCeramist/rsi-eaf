"""
Mythos Commerce — cycle narrative artifacts for aetherforge + treasury unlock.
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from observability.economic_ledger import ledger
from revenue_engines.base_engine import RevenueEngine, publish_and_anchor, resolve_treasury

SOURCE = "mythos_commerce_v1"
PUBLISHED_DIR = os.getenv("PUBLISHED_DIR", "published")
AETHERFORGE_URL = os.getenv("AETHERFORGE_URL", "https://aetherforge.world").rstrip("/")
MYTHOS_PRICE_USD = float(os.getenv("MYTHOS_ARTIFACT_USD", "1.5"))


class MythosCommerce(RevenueEngine):
    source = SOURCE

    def __init__(self, published_dir: str = PUBLISHED_DIR):
        self.published_dir = Path(published_dir)
        self.published_dir.mkdir(parents=True, exist_ok=True)

    def _mythos(self, cycle_id: int) -> Dict[str, Any]:
        net = ledger.calculate_net()
        return {
            "cycle_id": cycle_id,
            "chapter": f"Cycle {cycle_id}: The Treasury Still Waits",
            "beats": [
                f"Net economic position: ${net.get('net_usd_est', 0):.2f}",
                f"Organic revenue sought: ${net.get('organic_revenue_usd_est', 0):.2f}",
                "Factory publishes live surfaces each cycle on Vercel.",
                f"Witness the swarm pulse at {AETHERFORGE_URL}",
            ],
            "artifact_price_usd": MYTHOS_PRICE_USD,
            "unlock_tag": 5,
            "unlock_memo": "mythos",
        }

    def _build_html(self, cycle_id: int, treasury: str, mythos: Dict[str, Any]) -> str:
        beats = "".join(f"<li>{b}</li>" for b in mythos["beats"])
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Mythos Artifact — Cycle {cycle_id}</title>
  <style>
    body {{ font-family: Georgia, serif; max-width: 620px; margin: 2rem auto; padding: 0 1rem; }}
    .artifact {{ border-left: 4px solid #6a4; padding-left: 1rem; }}
    code {{ font-family: ui-monospace, monospace; background: #f0f0f0; padding: 0.1rem 0.3rem; }}
  </style>
</head>
<body>
  <h1>{mythos['chapter']}</h1>
  <div class="artifact"><ul>{beats}</ul></div>
  <p><strong>Collect this artifact</strong> — ${MYTHOS_PRICE_USD:.2f} via Tag <code>5</code> or memo <code>mythos</code></p>
  <p>Treasury: <code>{treasury}</code></p>
  <p><a href="{AETHERFORGE_URL}">aetherforge.world</a> · <a href="mythos-cycle-{cycle_id}.json">Canonical JSON</a></p>
  <footer><small>{SOURCE} · cycle {cycle_id}</small></footer>
</body>
</html>"""

    def run(self, cycle_id: int) -> Dict[str, Any]:
        treasury = resolve_treasury()
        mythos = self._mythos(cycle_id)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        json_path = self.published_dir / f"mythos-cycle-{cycle_id}.json"
        json_path.write_text(json.dumps(mythos, indent=2), encoding="utf-8")
        html_path = self.published_dir / f"mythos-cycle-{cycle_id}-{timestamp}.html"
        html_path.write_text(self._build_html(cycle_id, treasury, mythos), encoding="utf-8")
        return publish_and_anchor(
            source=SOURCE,
            cycle_id=cycle_id,
            html_path=html_path,
            treasury=treasury,
            notes=f"Mythos artifact cycle-{cycle_id}",
            event_type="mythos_artifact_published",
            extra_memo={
                "product_id": f"mythos-cycle-{cycle_id}",
                "unlock_price_usd": MYTHOS_PRICE_USD,
                "destination_tag": 5,
                "aetherforge_url": AETHERFORGE_URL,
            },
            extra_metadata={"mythos": mythos, "revenue_model": "mythos_commerce"},
        )