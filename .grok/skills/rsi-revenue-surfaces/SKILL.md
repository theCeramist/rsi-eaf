---
name: rsi-revenue-surfaces
description: RSI-EAF revenue surface patterns — Vercel publish, tip manifest, GitHub gist, aetherforge CTA.
---

# RSI Revenue Surfaces

Canonical surfaces for external XRPL payments:

- **Treasury:** `FACTORY_TREASURY_ADDRESS` on XRPL testnet
- **Tip:** Destination Tag `1` → $1.00 verified
- **Briefing:** Tag `2` or memo `briefing` + `product_id: briefing-cycle-{N}` → $2.00
- **Live index:** `FACTORY_PUBLIC_BASE_URL` (published-zeta.vercel.app)
- **Manifest:** `/tip-manifest.json` — agent-readable JSON
- **Gist:** public gist via `tools/gist_distribution.py`
- **GitHub issue #1:** support + cycle milestone comments
- **aetherforge:** `revenue_cta` in nexus wave → jarvis-swarm push

Always prefer **current cycle** tip URL (`PREFER_CURRENT_CYCLE_TIP=true`).