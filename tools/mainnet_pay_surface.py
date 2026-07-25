"""
Professional mainnet-capable pay.html + dual manifests for first real revenue.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

PUB = Path(os.getenv("PUBLISHED_DIR", "published"))


def build_pay_html(
    *,
    treasury: str,
    network: str,
    cycle_id: int = 0,
    base_url: str = "",
    explorer_account: str = "",
    secondary_treasury: Optional[str] = None,
    secondary_network: Optional[str] = None,
) -> str:
    base = (base_url or os.getenv("FACTORY_PUBLIC_BASE_URL", "https://published-zeta.vercel.app")).rstrip("/")
    net_label = "XRPL Mainnet" if network == "mainnet" else "XRPL Testnet"
    net_badge = "MAINNET · REAL XRP" if network == "mainnet" else "TESTNET"
    accent = "#00d4aa" if network == "mainnet" else "#7aa2ff"
    secondary_block = ""
    if secondary_treasury and secondary_network and secondary_treasury != treasury:
        sec_label = "Mainnet" if secondary_network == "mainnet" else "Testnet"
        secondary_block = f"""
<section class="card muted">
  <h2>Also accepting ({sec_label})</h2>
  <p class="mono">{secondary_treasury}</p>
  <p class="small">Same Destination Tags. Prefer the primary treasury above for production payers.</p>
</section>
"""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Pay RSI-EAF · {net_label}</title>
<meta name="description" content="Pay the RSI-EAF autonomous economic factory on {net_label}. Destination Tag 1 = verified tip."/>
<meta property="og:title" content="Pay RSI-EAF · {net_label}"/>
<meta property="og:description" content="Real XRPL payments to factory treasury. Tag 1 tip · Tag 2 briefing · Tag 3 tool."/>
<meta property="og:url" content="{base}/pay.html"/>
<link rel="canonical" href="{base}/pay.html"/>
<style>
:root {{ --bg:#070b12; --card:#101826; --text:#e8eef7; --muted:#8b9bb4; --accent:{accent}; --border:#1e2a3d; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, sans-serif; background:radial-gradient(1200px 600px at 20% -10%, #12203a 0%, var(--bg) 55%); color:var(--text); line-height:1.5; }}
.wrap {{ max-width:720px; margin:0 auto; padding:2rem 1.25rem 4rem; }}
.badge {{ display:inline-block; font-size:.72rem; letter-spacing:.08em; font-weight:700; color:#04120e; background:var(--accent); padding:.35rem .65rem; border-radius:999px; }}
h1 {{ font-size:1.85rem; margin:.9rem 0 .4rem; letter-spacing:-.02em; }}
.lead {{ color:var(--muted); margin:0 0 1.5rem; }}
.card {{ background:var(--card); border:1px solid var(--border); border-radius:16px; padding:1.25rem 1.35rem; margin:1rem 0; box-shadow:0 12px 40px rgba(0,0,0,.25); }}
.card.muted {{ opacity:.92; }}
.mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; word-break:break-all; font-size:.95rem; background:#0a1220; padding:.85rem 1rem; border-radius:10px; border:1px solid var(--border); }}
.row {{ display:flex; gap:.75rem; flex-wrap:wrap; margin-top:1rem; }}
.cta {{ display:inline-block; background:var(--accent); color:#04120e; text-decoration:none; font-weight:700; padding:.75rem 1.1rem; border-radius:10px; }}
.cta.ghost {{ background:transparent; color:var(--text); border:1px solid var(--border); }}
table {{ width:100%; border-collapse:collapse; font-size:.92rem; }}
th, td {{ text-align:left; padding:.55rem .35rem; border-bottom:1px solid var(--border); }}
th {{ color:var(--muted); font-weight:600; }}
.small {{ color:var(--muted); font-size:.85rem; }}
.ok {{ color:var(--accent); font-weight:600; }}
footer {{ margin-top:2rem; color:var(--muted); font-size:.8rem; }}
</style>
</head>
<body>
<main class="wrap">
  <span class="badge">{net_badge}</span>
  <h1>Pay the RSI-EAF factory</h1>
  <p class="lead">Autonomous economic agent factory. Verifiable XRPL payments. Exclusive ICP. Not for everyone.</p>

  <section class="card">
    <h2>Primary treasury · {net_label}</h2>
    <p class="mono" id="treasury">{treasury}</p>
    <p class="small">Explorer: <a href="{explorer_account or '#'}" style="color:var(--accent)">{explorer_account or "xrpl.org"}</a></p>
    <div class="row">
      <a class="cta" href="{base}/agent-pay.json">agent-pay.json</a>
      <a class="cta ghost" href="{base}/tip-manifest.json">tip-manifest.json</a>
      <a class="cta ghost" href="{base}/network-status.json">network-status.json</a>
    </div>
  </section>

  <section class="card">
    <h2>Easiest path (humans + agents)</h2>
    <ol>
      <li>Open any XRPL wallet on <strong>{net_label}</strong></li>
      <li>Send XRP to the treasury address above</li>
      <li>Set <strong>Destination Tag = 1</strong></li>
      <li>Memo optional — blank is fine</li>
    </ol>
    <p class="ok">Tag 1 credits ≈ $1 verified organic tip after on-ledger confirmation.</p>
  </section>

  <section class="card">
    <h2>Destination tags</h2>
    <table>
      <thead><tr><th>Tag</th><th>Product</th><th>Est. USD</th></tr></thead>
      <tbody>
        <tr><td>1</td><td>Tip / support</td><td>$1</td></tr>
        <tr><td>2</td><td>Paid briefing unlock</td><td>$2–5</td></tr>
        <tr><td>3</td><td>Micro-tool / validator spec</td><td>$3</td></tr>
        <tr><td>4</td><td>Agent service bundle</td><td>$2.5–10</td></tr>
        <tr><td>5</td><td>Mythos artifact</td><td>$2</td></tr>
      </tbody>
    </table>
  </section>

  {secondary_block}

  <section class="card">
    <h2>Agent integrators</h2>
    <p class="small">Machine contract: <a style="color:var(--accent)" href="{base}/agent-pay.json">{base}/agent-pay.json</a></p>
    <p class="small">x402 discovery: <a style="color:var(--accent)" href="{base}/.well-known/x402.json">{base}/.well-known/x402.json</a></p>
    <p class="small">ICP doctrine: <a style="color:var(--accent)" href="{base}/icp.json">{base}/icp.json</a></p>
  </section>

  <footer>
    RSI-EAF cycle {cycle_id} · network={network} · generated {datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")}
    · Ground truth: XRPL tx hash + economic ledger · No spoofed revenue
  </footer>
</main>
<script>
// Copy treasury on click
document.getElementById('treasury')?.addEventListener('click', async () => {{
  try {{ await navigator.clipboard.writeText({json.dumps(treasury)}); }} catch (e) {{}}
}});
</script>
</body>
</html>
"""


def write_mainnet_pay_surface(cycle_id: int = 0) -> Dict[str, Any]:
    from factory_core.xrpl_network import (
        explorer_account_url,
        mainnet_treasury_address,
        network_label,
        resolve_public_treasury,
        testnet_treasury_address,
        write_readiness_artifacts,
    )

    pub_addr, pub_net = resolve_public_treasury()
    secondary = None
    secondary_net = None
    mn = mainnet_treasury_address()
    tn = testnet_treasury_address()
    if pub_net == "mainnet" and tn and tn != pub_addr:
        secondary, secondary_net = tn, "testnet"
    elif pub_net == "testnet" and mn and mn != pub_addr:
        secondary, secondary_net = mn, "mainnet"

    readiness = write_readiness_artifacts(cycle_id)
    html = build_pay_html(
        treasury=pub_addr,
        network=pub_net,
        cycle_id=cycle_id,
        explorer_account=explorer_account_url(pub_addr, pub_net),
        secondary_treasury=secondary,
        secondary_network=secondary_net,
    )
    PUB.mkdir(parents=True, exist_ok=True)
    (PUB / "pay.html").write_text(html, encoding="utf-8")
    (PUB / "archive").mkdir(parents=True, exist_ok=True)
    (PUB / "archive" / "pay.html").write_text(html, encoding="utf-8")

    # dual treasury map for agents
    dual = {
        "schema": "rsi_eaf_treasury_map_v1",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "cycle_id": cycle_id,
        "primary": {
            "network": pub_net,
            "label": network_label(pub_net),
            "address": pub_addr,
            "explorer": explorer_account_url(pub_addr, pub_net),
            "role": "public_revenue",
        },
        "testnet": {"address": tn, "explorer": explorer_account_url(tn, "testnet") if tn else None},
        "mainnet": {"address": mn, "explorer": explorer_account_url(mn, "mainnet") if mn else None},
        "destination_tag_tip": 1,
        "safety": readiness.get("safety"),
    }
    (PUB / "treasury-map.json").write_text(json.dumps(dual, indent=2), encoding="utf-8")
    return {
        "pay_html": str(PUB / "pay.html"),
        "treasury": pub_addr,
        "network": pub_net,
        "readiness": readiness.get("ready_accept_unfunded", {}).get("ready"),
        "dual": dual,
    }
