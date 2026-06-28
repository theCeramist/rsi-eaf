"""
Micro-SaaS Tool Factory — cycle-scoped micro-tool landing pages with usage-priced CTAs.
"""

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from factory_core.revenue_fitness import evaluate_revenue_models
from revenue_engines.base_engine import RevenueEngine, publish_and_anchor, resolve_treasury

SOURCE = "micro_saas_factory_v1"
PUBLISHED_DIR = os.getenv("PUBLISHED_DIR", "published")
MICRO_SAAS_PRICE_USD = float(os.getenv("MICRO_SAAS_UNLOCK_USD", "3.0"))


class MicroSaasFactory(RevenueEngine):
    source = SOURCE

    def __init__(self, published_dir: str = PUBLISHED_DIR):
        self.published_dir = Path(published_dir)
        self.published_dir.mkdir(parents=True, exist_ok=True)

    def _opportunity(self, cycle_id: int) -> Dict[str, str]:
        fitness = evaluate_revenue_models()
        top = fitness["top3"][0]
        return {
            "title": f"XRPL Treasury Tip Validator (cycle {cycle_id})",
            "problem": "Agents and humans struggle to verify testnet tip memos and destination tags.",
            "solution": "One-click validator page + agent manifest hooks for RSI-EAF treasury.",
            "pricing": f"${MICRO_SAAS_PRICE_USD:.2f} per unlock via Destination Tag 3 or memo 'tool'",
            "fitness_model": top["name"],
            "fitness_score": str(top["fitness"]),
        }

    def _build_html(self, cycle_id: int, treasury: str, opp: Dict[str, str]) -> str:
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{opp['title']}</title>
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 640px; margin: 2rem auto; padding: 0 1rem; }}
    .cta {{ background: #0a7; color: #fff; padding: 1rem; border-radius: 8px; }}
    code {{ background: #f4f4f4; padding: 0.15rem 0.4rem; border-radius: 4px; }}
  </style>
</head>
<body>
  <h1>{opp['title']}</h1>
  <p><strong>Problem:</strong> {opp['problem']}</p>
  <p><strong>Micro-tool:</strong> {opp['solution']}</p>
  <div class="cta">
    <p><strong>Unlock full validator</strong> — {opp['pricing']}</p>
    <p>Treasury: <code>{treasury}</code><br>
       Destination Tag: <code>3</code> or memo <code>tool</code></p>
  </div>
  <p>Fitness anchor: {opp['fitness_model']} ({opp['fitness_score']}/100)</p>
  <p><a href="tip-manifest.json">Agent manifest</a> · <a href="service-catalog.json">Service catalog</a></p>
  <footer><small>{SOURCE} · cycle {cycle_id}</small></footer>
</body>
</html>"""

    def run(self, cycle_id: int) -> Dict[str, Any]:
        treasury = resolve_treasury()
        opp = self._opportunity(cycle_id)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        slug = f"micro-tool-cycle-{cycle_id}-{timestamp}"
        html_path = self.published_dir / f"{slug}.html"
        html_path.write_text(self._build_html(cycle_id, treasury, opp), encoding="utf-8")
        return publish_and_anchor(
            source=SOURCE,
            cycle_id=cycle_id,
            html_path=html_path,
            treasury=treasury,
            notes=f"Micro-SaaS surface {slug}",
            event_type="micro_saas_published",
            extra_memo={
                "product_id": f"micro-tool-cycle-{cycle_id}",
                "unlock_price_usd": MICRO_SAAS_PRICE_USD,
                "destination_tag": 3,
            },
            extra_metadata={"opportunity": opp, "revenue_model": "micro_saas"},
        )