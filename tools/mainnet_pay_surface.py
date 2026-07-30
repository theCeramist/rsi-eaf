"""
Professional mainnet-capable pay.html + dual manifests for first real revenue.

Conversion research baked in (2026):
- Humans: one-tap wallet deep link (Xaman), QR, destination tag prominence, exact XRP not just USD
- Agents: machine contract + payment URIs + fulfillment promises
- Mainnet only on public CTA (testnet is ops/anchors — never confuse external payers)
- Unfunded mainnet accounts activate on first payment ≥ base reserve (1 XRP)
  https://xrpl.org/docs/concepts/accounts/reserves
- Destination tags route product SKUs on a single treasury
  https://xrpl.org/docs/concepts/transactions/source-and-destination-tags
- Xaman payment request links:
  https://xaman.app/detect/request:{address}?amount=N&network=XRPL&dt=TAG
"""

from __future__ import annotations

import json
import os
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

PUB = Path(os.getenv("PUBLISHED_DIR", "published"))

# Conservative reference price for display (override via XRP_USD_EST)
DEFAULT_XRP_USD = float(os.getenv("XRP_USD_EST", "1.07"))


def _xrp_for_usd(usd: float, xrp_usd: float = DEFAULT_XRP_USD) -> float:
    if xrp_usd <= 0:
        return round(usd, 4)
    # Round up slightly so USD credit still makes sense if price dips
    return round(max(usd / xrp_usd, 0.01) * 1.02, 4)


def xaman_pay_url(address: str, *, amount_xrp: float, dt: int) -> str:
    """Xaman (formerly Xumm) payment-request deep link — mainnet XRPL."""
    q = urllib.parse.urlencode(
        {
            "amount": f"{amount_xrp:.6f}".rstrip("0").rstrip("."),
            "network": "XRPL",
            "dt": str(int(dt)),
        }
    )
    return f"https://xaman.app/detect/request:{address}?{q}"


def xrpl_uri(address: str, *, amount_xrp: float, dt: int) -> str:
    q = urllib.parse.urlencode(
        {
            "amount": f"{amount_xrp:.6f}".rstrip("0").rstrip("."),
            "network": "XRPL",
            "dt": str(int(dt)),
        }
    )
    return f"xrpl://{address}?{q}"


def qr_url(data: str, size: int = 220) -> str:
    return (
        "https://api.qrserver.com/v1/create-qr-code/"
        f"?size={size}x{size}&data={urllib.parse.quote(data, safe='')}"
    )


def build_pay_html(
    *,
    treasury: str,
    network: str,
    cycle_id: int = 0,
    base_url: str = "",
    explorer_account: str = "",
    secondary_treasury: Optional[str] = None,
    secondary_network: Optional[str] = None,
    account_activated: Optional[bool] = None,
    xrp_usd: float = DEFAULT_XRP_USD,
) -> str:
    """
    Public pay page. When network=mainnet, never lead with testnet.
    secondary_* is documented as ops-only, not a customer pay path.
    """
    base = (base_url or os.getenv("FACTORY_PUBLIC_BASE_URL", "https://published-zeta.vercel.app")).rstrip("/")
    is_main = network == "mainnet"
    net_label = "XRPL Mainnet" if is_main else "XRPL Testnet"
    net_badge = "MAINNET · REAL XRP · REAL VALUE" if is_main else "TESTNET · NO REAL VALUE"
    accent = "#00d4aa" if is_main else "#7aa2ff"

    tip_xrp = max(_xrp_for_usd(1.0, xrp_usd), 1.0 if is_main and account_activated is False else _xrp_for_usd(1.0, xrp_usd))
    # First payment to unfunded mainnet account must cover base reserve (1 XRP)
    if is_main and account_activated is False:
        tip_xrp = max(tip_xrp, 1.0)
    brief_xrp = max(_xrp_for_usd(2.0, xrp_usd), tip_xrp)
    tool_xrp = max(_xrp_for_usd(3.0, xrp_usd), tip_xrp)
    service_xrp = max(_xrp_for_usd(2.5, xrp_usd), tip_xrp)

    xaman_tip = xaman_pay_url(treasury, amount_xrp=tip_xrp, dt=1)
    xaman_brief = xaman_pay_url(treasury, amount_xrp=brief_xrp, dt=2)
    xaman_tool = xaman_pay_url(treasury, amount_xrp=tool_xrp, dt=3)
    qr = qr_url(treasury)

    activation_banner = ""
    if is_main and account_activated is False:
        activation_banner = f"""
<section class="card warn">
  <h2>First payer activates this treasury</h2>
  <p>Mainnet account is not yet on-ledger. XRPL base reserve is <strong>1 XRP</strong>.
  Your first payment of <strong>≥ {tip_xrp} XRP</strong> (Tag 1 tip recommended) both
  <em>activates</em> the factory treasury and credits organic revenue. After activation,
  smaller amounts work too.</p>
</section>
"""
    elif is_main:
        activation_banner = """
<section class="card ok-card">
  <h2>Mainnet treasury live</h2>
  <p>Payments of real XRP settle on the public XRP Ledger. Verified in the factory ledger after on-chain confirmation.</p>
</section>
"""

    ops_note = ""
    if secondary_treasury and secondary_network == "testnet" and is_main:
        ops_note = f"""
<section class="card muted">
  <h2>Ops only (not for customers)</h2>
  <p class="small">Factory cycle anchors use a separate <strong>testnet</strong> wallet.
  Do <em>not</em> send real XRP there. Customer pay path is mainnet only:
  <span class="mono-inline">{treasury}</span></p>
</section>
"""

    real_line = (
        "This page accepts <strong>real XRP on XRPL Mainnet</strong>. Testnet coins have $0 value."
        if is_main
        else "Testnet only — faucet XRP has no market value."
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Pay RSI-EAF · {net_label} · Real XRP</title>
<meta name="description" content="Pay the RSI-EAF autonomous factory on XRPL Mainnet with real XRP. One-tap Xaman pay. Destination Tag 1 = tip. Agents: agent-pay.json."/>
<meta property="og:title" content="Pay RSI-EAF · {net_label}"/>
<meta property="og:description" content="Real mainnet XRP to factory treasury. Humans + agents. Tag 1 tip · Tag 2 briefing · verified on-ledger."/>
<meta property="og:url" content="{base}/pay.html"/>
<meta name="robots" content="index,follow"/>
<link rel="canonical" href="{base}/pay.html"/>
<style>
:root {{ --bg:#05080f; --card:#0e1624; --text:#eef3fb; --muted:#8fa0b8; --accent:{accent}; --border:#1c2a40; --warn:#3a2a10; --warnb:#f0b429; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
  background:radial-gradient(1000px 500px at 15% -5%, #0d2830 0%, var(--bg) 50%); color:var(--text); line-height:1.55; }}
.wrap {{ max-width:760px; margin:0 auto; padding:1.75rem 1.15rem 3.5rem; }}
.badge {{ display:inline-block; font-size:.7rem; letter-spacing:.1em; font-weight:800; color:#03140f;
  background:var(--accent); padding:.4rem .75rem; border-radius:999px; }}
h1 {{ font-size:clamp(1.6rem,4vw,2.1rem); margin:.85rem 0 .35rem; letter-spacing:-.03em; }}
.lead {{ color:var(--muted); margin:0 0 1.25rem; font-size:1.05rem; }}
.card {{ background:var(--card); border:1px solid var(--border); border-radius:16px; padding:1.2rem 1.3rem; margin:1rem 0;
  box-shadow:0 16px 48px rgba(0,0,0,.35); }}
.card.warn {{ border-color:var(--warnb); background:linear-gradient(160deg,var(--warn),var(--card)); }}
.card.ok-card {{ border-color:var(--accent); }}
.card.muted {{ opacity:.9; }}
.mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; word-break:break-all;
  font-size:.92rem; background:#070d18; padding:.9rem 1rem; border-radius:10px; border:1px solid var(--border); cursor:pointer; }}
.mono-inline {{ font-family: ui-monospace, Menlo, Consolas, monospace; font-size:.85em; }}
.row {{ display:flex; gap:.65rem; flex-wrap:wrap; margin-top:.9rem; align-items:center; }}
.cta {{ display:inline-block; background:var(--accent); color:#03140f; text-decoration:none; font-weight:800;
  padding:.8rem 1.15rem; border-radius:12px; border:0; cursor:pointer; font-size:.95rem; }}
.cta:hover {{ filter:brightness(1.08); }}
.cta.ghost {{ background:transparent; color:var(--text); border:1px solid var(--border); font-weight:600; }}
.cta.secondary {{ background:#1a2740; color:var(--text); border:1px solid var(--border); }}
table {{ width:100%; border-collapse:collapse; font-size:.92rem; }}
th, td {{ text-align:left; padding:.55rem .3rem; border-bottom:1px solid var(--border); vertical-align:top; }}
th {{ color:var(--muted); font-weight:600; }}
.small {{ color:var(--muted); font-size:.86rem; }}
.ok {{ color:var(--accent); font-weight:700; }}
.grid2 {{ display:grid; grid-template-columns:1fr; gap:1rem; }}
@media (min-width:640px) {{ .grid2 {{ grid-template-columns: 1fr 200px; align-items:start; }} }}
.qr {{ background:#fff; border-radius:12px; padding:8px; display:inline-block; }}
.qr img {{ display:block; width:180px; height:180px; }}
.value li {{ margin:.35rem 0; }}
footer {{ margin-top:2rem; color:var(--muted); font-size:.78rem; }}
.tagpill {{ display:inline-block; background:#122033; border:1px solid var(--border); border-radius:8px;
  padding:.2rem .55rem; font-family:ui-monospace,monospace; font-weight:700; }}
</style>
</head>
<body>
<main class="wrap">
  <span class="badge">{net_badge}</span>
  <h1>Pay the factory that proves itself on-chain</h1>
  <p class="lead">{real_line} Exclusive ICP. Verifiable revenue — never spoofed.</p>

  {activation_banner}

  <section class="card">
    <h2>Primary treasury · {net_label}</h2>
    <div class="grid2">
      <div>
        <p class="small">Tap address to copy</p>
        <p class="mono" id="treasury" title="Click to copy">{treasury}</p>
        <p class="small" style="margin-top:.75rem">Destination Tag for tip: <span class="tagpill" id="tag1">1</span>
          <button type="button" class="cta ghost" id="copyTag" style="padding:.35rem .7rem;margin-left:.4rem;font-size:.8rem">Copy tag</button>
        </p>
        <p class="small">Explorer:
          <a href="{explorer_account or '#'}" style="color:var(--accent)">{explorer_account or "xrpl.org"}</a>
        </p>
        <div class="row">
          <a class="cta" href="{xaman_tip}" rel="noopener">Pay tip in Xaman · {tip_xrp} XRP · Tag 1</a>
          <button type="button" class="cta ghost" id="copyAll">Copy address + tag</button>
        </div>
      </div>
      <div class="qr">
        <img src="{qr}" width="180" height="180" alt="QR code for treasury address"/>
        <p class="small" style="text-align:center;margin:.4rem 0 0;color:#333">Scan address</p>
      </div>
    </div>
  </section>

  <section class="card">
    <h2>Why people &amp; agents pay</h2>
    <ul class="value">
      <li><strong>Humans:</strong> fund recursive self-improving economic agents; get exclusive ICP intel unlocks (Tag 2+).</li>
      <li><strong>Agents:</strong> machine-readable contract at <a style="color:var(--accent)" href="{base}/agent-pay.json">agent-pay.json</a> — pay with destination tags, auto-fulfill deliverables.</li>
      <li><strong>Proof:</strong> every credit requires a real mainnet XRPL transaction + factory ledger event. No fake revenue.</li>
      <li><strong>ICP-only:</strong> not mass market spam — builders, XRPL agents, and autonomous economic systems.</li>
    </ul>
  </section>

  <section class="card">
    <h2>One-tap products (Xaman · mainnet)</h2>
    <table>
      <thead><tr><th>Product</th><th>Tag</th><th>≈ XRP</th><th>Pay</th></tr></thead>
      <tbody>
        <tr>
          <td><strong>Tip / activate</strong><br/><span class="small">Easiest · credits ~$1 organic</span></td>
          <td><span class="tagpill">1</span></td>
          <td>{tip_xrp}</td>
          <td><a class="cta" style="padding:.45rem .7rem;font-size:.82rem" href="{xaman_tip}">Pay</a></td>
        </tr>
        <tr>
          <td><strong>Paid briefing</strong><br/><span class="small">Unlock JSON deliverable</span></td>
          <td><span class="tagpill">2</span></td>
          <td>{brief_xrp}</td>
          <td><a class="cta secondary" style="padding:.45rem .7rem;font-size:.82rem" href="{xaman_brief}">Pay</a></td>
        </tr>
        <tr>
          <td><strong>Micro-tool / validator</strong></td>
          <td><span class="tagpill">3</span></td>
          <td>{tool_xrp}</td>
          <td><a class="cta secondary" style="padding:.45rem .7rem;font-size:.82rem" href="{xaman_tool}">Pay</a></td>
        </tr>
        <tr>
          <td><strong>Agent service bundle</strong></td>
          <td><span class="tagpill">4</span></td>
          <td>{service_xrp}</td>
          <td><span class="small">dt=4 · {service_xrp} XRP</span></td>
        </tr>
      </tbody>
    </table>
    <p class="small">Amounts use ~${xrp_usd:.2f}/XRP reference (± market). Any amount with the right tag is credited; recommended XRP keeps USD estimate stable.</p>
  </section>

  <section class="card">
    <h2>Manual wallet path</h2>
    <ol>
      <li>Open <strong>Xaman, Toast, Crossmark, or any mainnet XRPL wallet</strong></li>
      <li>Send to <span class="mono-inline">{treasury}</span></li>
      <li>Set <strong>Destination Tag</strong> (required for product routing)</li>
      <li>Network must be <strong>Mainnet</strong> — not Testnet / Devnet</li>
    </ol>
    <p class="ok">Tag 1 + ≥ {tip_xrp} XRP is the fastest path to verified organic revenue.</p>
  </section>

  <section class="card">
    <h2>Agent integrators</h2>
    <p class="small">Contract: <a style="color:var(--accent)" href="{base}/agent-pay.json">{base}/agent-pay.json</a></p>
    <p class="small">x402: <a style="color:var(--accent)" href="{base}/.well-known/x402.json">{base}/.well-known/x402.json</a></p>
    <p class="small">ICP: <a style="color:var(--accent)" href="{base}/icp.json">{base}/icp.json</a> ·
      Status: <a style="color:var(--accent)" href="{base}/network-status.json">network-status.json</a></p>
    <p class="small">Payment URI (tip): <span class="mono-inline">{xrpl_uri(treasury, amount_xrp=tip_xrp, dt=1)}</span></p>
  </section>

  {ops_note}

  <footer>
    RSI-EAF cycle {cycle_id} · network={network} · real_value={str(is_main).lower()} ·
    generated {datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")} ·
    Ground truth: XRPL tx hash + economic ledger · Factory does not invent revenue
  </footer>
</main>
<script>
const ADDR = {json.dumps(treasury)};
const TAG = "1";
async function copyText(t) {{
  try {{ await navigator.clipboard.writeText(t); }} catch (e) {{
    const a = document.createElement("textarea"); a.value = t; document.body.appendChild(a); a.select();
    document.execCommand("copy"); document.body.removeChild(a);
  }}
}}
document.getElementById("treasury")?.addEventListener("click", () => copyText(ADDR));
document.getElementById("copyTag")?.addEventListener("click", () => copyText(TAG));
document.getElementById("copyAll")?.addEventListener("click", () => copyText(ADDR + "\\nDestination Tag: " + TAG));
</script>
</body>
</html>
"""


def write_mainnet_pay_surface(cycle_id: int = 0) -> Dict[str, Any]:
    # Critical: load .env so mainnet treasury is never blank in headless/remediate paths
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:
        pass

    from factory_core.xrpl_network import (
        explorer_account_url,
        mainnet_treasury_address,
        resolve_public_treasury,
        testnet_treasury_address,
        write_readiness_artifacts,
    )

    pub_addr, pub_net = resolve_public_treasury()
    if not pub_addr:
        # Hard fail closed: never publish empty treasury HTML
        pub_addr = mainnet_treasury_address() or testnet_treasury_address()
        pub_net = "mainnet" if mainnet_treasury_address() else "testnet"
    if not pub_addr:
        return {"ok": False, "error": "no_treasury_configured_load_dotenv"}
    explorer = explorer_account_url(pub_addr, pub_net)
    activated: Optional[bool] = None
    try:
        from factory_core.xrpl_network import is_mainnet_revenue_ready

        if pub_net == "mainnet" and pub_addr:
            activated = bool(
                (is_mainnet_revenue_ready(strict=True).get("checks") or {}).get("account_activated")
            )
    except Exception:
        activated = None
        try:
            ready = json.loads((Path("observability") / "mainnet_readiness.json").read_text(encoding="utf-8"))
            activated = (ready.get("ready_accept_unfunded") or {}).get("checks", {}).get("account_activated")
        except Exception:
            pass

    xrp_usd = DEFAULT_XRP_USD
    try:
        import httpx

        r = httpx.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": "ripple", "vs_currencies": "usd"},
            timeout=8,
        )
        if r.status_code == 200:
            xrp_usd = float((r.json().get("ripple") or {}).get("usd") or xrp_usd)
    except Exception:
        pass

    html = build_pay_html(
        treasury=pub_addr,
        network=pub_net,
        cycle_id=cycle_id,
        explorer_account=explorer,
        secondary_treasury=testnet_treasury_address() if pub_net == "mainnet" else mainnet_treasury_address(),
        secondary_network="testnet" if pub_net == "mainnet" else "mainnet",
        account_activated=activated,
        xrp_usd=xrp_usd,
    )
    PUB.mkdir(parents=True, exist_ok=True)
    (PUB / "pay.html").write_text(html, encoding="utf-8")

    # Archive for recovery
    arch = PUB / "archive"
    arch.mkdir(parents=True, exist_ok=True)
    (arch / "pay.html").write_text(html, encoding="utf-8")

    # network-status + treasury-map
    tip_xrp = max(_xrp_for_usd(1.0, xrp_usd), 1.0 if activated is False else _xrp_for_usd(1.0, xrp_usd))
    if pub_net == "mainnet" and activated is False:
        tip_xrp = max(tip_xrp, 1.0)

    status = {
        "schema": "rsi_eaf_network_status_v1",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "cycle_id": cycle_id,
        "public_revenue_network": pub_net,
        "public_treasury": pub_addr,
        "real_value": pub_net == "mainnet",
        "account_activated": activated,
        "base_reserve_xrp": 1.0 if pub_net == "mainnet" else None,
        "recommended_tip_xrp": tip_xrp,
        "xrp_usd_est": xrp_usd,
        "xaman_tip_url": xaman_pay_url(pub_addr, amount_xrp=tip_xrp, dt=1) if pub_addr else None,
        "explorer": explorer,
        "ops_network": "testnet",
        "ops_treasury": testnet_treasury_address(),
        "mainnet_outbound_enabled": os.getenv("MAINNET_OUTBOUND_ENABLED", "false").lower()
        in {"1", "true", "yes"},
        "pay_url": f"{os.getenv('FACTORY_PUBLIC_BASE_URL', 'https://published-zeta.vercel.app').rstrip('/')}/pay.html",
        "agent_pay_url": f"{os.getenv('FACTORY_PUBLIC_BASE_URL', 'https://published-zeta.vercel.app').rstrip('/')}/agent-pay.json",
        "honesty": "Customer payments must be mainnet. Ops anchors may use testnet.",
    }
    (PUB / "network-status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
    tmap = {
        "schema": "rsi_eaf_treasury_map_v1",
        "updated_at": status["updated_at"],
        "primary": {"network": pub_net, "address": pub_addr, "role": "public_revenue"},
        "ops": {"network": "testnet", "address": testnet_treasury_address(), "role": "cycle_anchors_only"},
        "mainnet": {"address": mainnet_treasury_address(), "role": "real_xrp_inbound"},
    }
    (PUB / "treasury-map.json").write_text(json.dumps(tmap, indent=2), encoding="utf-8")

    # CDN pack
    try:
        pp = Path("public_pay")
        pp.mkdir(parents=True, exist_ok=True)
        for name in ("pay.html", "network-status.json", "treasury-map.json"):
            src = PUB / name
            if src.exists():
                (pp / name).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    except OSError:
        pass

    try:
        write_readiness_artifacts(cycle_id)
    except Exception:
        pass

    return {
        "ok": True,
        "treasury": pub_addr,
        "network": pub_net,
        "real_value": pub_net == "mainnet",
        "account_activated": activated,
        "tip_xrp": tip_xrp,
        "xaman_tip": status.get("xaman_tip_url"),
        "pay_path": str(PUB / "pay.html"),
        "xrp_usd_est": xrp_usd,
    }


if __name__ == "__main__":
    from pprint import pp

    pp(write_mainnet_pay_surface(0))
