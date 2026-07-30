"""
RSI-EAF Social Media Policy — Receipts Social (v1).

Standards (owner):
  Human ICP  = @thatcrypto_guy-class (critical, anti-hype, wants prove)
  Agent ICP  = most sophisticated settlement agents only
  Posture    = grandiose ambition + practical artifacts
  Scoreboard = external organic payers, not impressions

This is NOT "exclusive spam with nicer words."
This is a public operating doctrine:

  1. PROOF BEFORE PITCH — every post carries a verifiable fact
  2. USEFUL BEFORE CTA  — teach or show something real first
  3. DUAL-CHANNEL       — humans read prose; agents parse rails
  4. SCARCITY           — few posts, high density; silence is brand
  5. REFUSAL IS CONTENT — publicly reject low-tier noise
  6. LEDGER IS SOCIAL   — metrics, cycles, tags, live URLs only

Novel frame: the factory's feed is a live economic instrument panel,
not a marketing channel.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE = os.getenv("FACTORY_PUBLIC_BASE_URL", "https://published-zeta.vercel.app").rstrip("/")
PAY = f"{BASE}/pay.html"
AGENT_PAY = f"{BASE}/agent-pay.json"
X402 = f"{BASE}/.well-known/x402"
ICP = f"{BASE}/icp.json"
POLICY = f"{BASE}/social-policy.json"
# Prefer mainnet public treasury for social hub links (real value)
try:
    from factory_core.xrpl_network import mainnet_treasury_address, resolve_public_treasury

    _pub, _net = resolve_public_treasury()
    _hub_addr = _pub or mainnet_treasury_address() or "rs78v3CbqDf5pDc6n7pyqg6LYaUnweLEH5"
except Exception:
    _hub_addr = os.getenv("FACTORY_MAINNET_TREASURY_ADDRESS", "rs78v3CbqDf5pDc6n7pyqg6LYaUnweLEH5")
HUB = f"https://xrpl.org/accounts/{_hub_addr}"
HUMAN = os.getenv("ICP_HUMAN_HANDLE", "thatcrypto_guy").lstrip("@")

POLICY_VERSION = "receipts_social_v1"

# Scarcity caps — automation that sprays gets accounts locked. Density over volume.
MAX_BROADCASTS_PER_DAY = int(os.getenv("SOCIAL_MAX_BROADCASTS_PER_DAY", "2"))
MAX_CALLOUTS_PER_DAY = int(os.getenv("SOCIAL_MAX_CALLOUTS_PER_DAY", "1"))
MIN_HOURS_BETWEEN_BROADCAST = float(os.getenv("SOCIAL_MIN_HOURS_BETWEEN_BROADCAST", "8"))


def policy_manifest() -> Dict[str, Any]:
    return {
        "schema": "rsi_eaf_social_policy_v1",
        "version": POLICY_VERSION,
        "name": "Receipts Social",
        "tagline": "The feed is an instrument panel — not a carnival.",
        "posture": "grandiose_practical_proof_first",
        "human_icp": {
            "handle": HUMAN,
            "bar": "critical crypto-native; overthinks; smells vapor; demands receipts",
        },
        "agent_icp": {
            "tier": "sophisticated_only",
            "bar": "x402 / tags / settle+verify; no toy bots",
        },
        "non_negotiables": [
            "PROOF BEFORE PITCH — live metric, cycle, tag, or artifact in every post",
            "USEFUL BEFORE CTA — free signal first; pay link second or absent",
            "DUAL-CHANNEL — prose for humans + machine rails for agents",
            "SCARCITY — density over volume; silence is intentional brand",
            "REFUSAL IS CONTENT — public no to airdrop/gm/builder LARP",
            "LEDGER IS SOCIAL — scoreboard is external organic payers only",
        ],
        "formats": {
            "RECEIPT": "Live factory fact (impressions, cycle, path, hub status) + one implication",
            "FAILURE": "Honest miss (gate, SLO, $0 organic cycle) + the fix in motion",
            "OFFER": "One useful free artifact (policy, intel, path) then optional Tag path",
            "REFUSAL": "Explicit reject of low-tier noise with why (brand, not cruelty)",
            "SIGNAL": "Point at someone else's real work; add one sharper frame; no generic CTA spam",
            "MACHINE": "Agent-only dense line: discovery URLs + tag discipline",
            "LEARNING": "Public self-improve: what the graph taught → next factory action",
        },
        "forbidden": [
            "GM / engagement bait",
            "Airdrop / whitelist / pump language",
            "Faucet tourism framing",
            "'Free merchant no signup for everyone'",
            "Raw r-address in tweets while X blocks crypto addresses",
            "Callouts with zero useful content relative to the target",
            "Unsolicited @-mention spam / mass callouts",
            "Burst likes / burst follows / identical cycle spam",
            "Advertising testnet as customer pay path (mainnet only for real value)",
            "Impression-chasing as success metric",
            "More than 1 pay-link post in any 3-post window (hard-mode)",
            "Two consecutive pay-link posts",
            "Any write after X lock/403 until cooldown elapses",
        ],
        "scarcity": {
            "max_broadcasts_per_day": MAX_BROADCASTS_PER_DAY,
            "max_callouts_per_day": MAX_CALLOUTS_PER_DAY,
            "min_hours_between_broadcast": MIN_HOURS_BETWEEN_BROADCAST,
            "max_pay_links_per_3_posts": 1,
            "no_consecutive_pay_links": True,
        },
        "self_improve_loop": {
            "social_interactions": "x_agent ticks + ICP hunt",
            "learning_engine": "factory_core.social_learning",
            "cycle_injection": "analyze lane + coordination directives",
            "evolution": "evolution_priorities_from_lessons → proposer",
            "public": f"{BASE}/social-learning.json",
        },
        "surfaces": {
            "pay": PAY,
            "agent_pay": AGENT_PAY,
            "x402": X402,
            "icp": ICP,
            "policy": POLICY,
            "learning": f"{BASE}/social-learning.json",
            "hub": HUB,
        },
        "success": {
            "primary": "external_organic_payer_on_ledger",
            "secondary": ["inbound_high_sophistication_mentions", "agent_discovery_hits"],
            "not_success": ["impressions_alone", "follow_count_alone", "self_pay"],
        },
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_live_facts() -> Dict[str, Any]:
    """Pull real artifacts so posts never invent vibes."""
    facts: Dict[str, Any] = {"at": _now()}
    analysis = Path("observability/x_agent_analysis_latest.json")
    state = Path("observability/x_agent_state.json")
    health = Path("observability/factory_health.json")
    try:
        if analysis.exists():
            a = json.loads(analysis.read_text(encoding="utf-8"))
            facts["path"] = a.get("critical_path")
            facts["totals"] = a.get("totals") or {}
            facts["next"] = (a.get("next_actions") or [])[:2]
    except (json.JSONDecodeError, OSError):
        pass
    try:
        if state.exists():
            s = json.loads(state.read_text(encoding="utf-8"))
            facts["metrics"] = s.get("public_metrics") or {}
            facts["handle"] = s.get("username") or os.getenv("X_HANDLE", "PM27319682")
    except (json.JSONDecodeError, OSError):
        pass
    try:
        if health.exists():
            h = json.loads(health.read_text(encoding="utf-8"))
            facts["cycle_id"] = h.get("cycle_id")
            facts["organic_revenue_usd"] = h.get("organic_revenue_usd") or h.get(
                "organic_revenue_usd_est"
            )
            facts["runner_active"] = h.get("runner_active")
            ledger = h.get("ledger_net") or {}
            if isinstance(ledger, dict):
                facts["net_usd"] = ledger.get("net_usd_est") or ledger.get("net")
    except (json.JSONDecodeError, OSError):
        pass
    return facts


def _apply_pay_hard_mode(text: str, *, wants_pay: bool = True) -> str:
    """Hard-mode: max 1 pay-link per 3 posts, never consecutive (social_learning)."""
    try:
        from factory_core.social_learning import enforce_pay_link_policy

        # If we don't want pay this format, strip first then enforce
        body = text
        if not wants_pay:
            from factory_core.social_learning import strip_pay_links

            body = strip_pay_links(text)
        return enforce_pay_link_policy(body).get("text") or body
    except Exception:
        return text


def format_receipt_pulse(facts: Optional[Dict[str, Any]] = None) -> str:
    """RECEIPT format — instrument panel post. Grandiose ambition, practical numbers."""
    f = facts or _load_live_facts()
    m = f.get("metrics") or {}
    t = f.get("totals") or {}
    path = f.get("path") or "unknown"
    cycle = f.get("cycle_id") or "?"
    organic = f.get("organic_revenue_usd")
    org_s = f"${organic:.2f}" if isinstance(organic, (int, float)) else "n/a"
    imp = t.get("impressions", m.get("tweet_count", "?"))
    follows = m.get("followers_count", "?")
    # Useful first: the operating truth. Pay rails optional under hard-mode.
    body = (
        f"RECEIPT · factory instrument panel\n"
        f"cycle {cycle} · path={path} · organic_revenue={org_s}\n"
        f"X: {follows} followers · ~{imp} impressions tracked · zero self-delusion\n"
        f"Human bar: @{HUMAN}-class · Agent bar: settle or skip\n"
        f"Rails: {PAY} · agents {AGENT_PAY}\n"
        f"Doctrine: {POLICY}"
    )
    return _apply_pay_hard_mode(body, wants_pay=True)


def format_failure_honesty(facts: Optional[Dict[str, Any]] = None) -> str:
    """FAILURE format — trust through admissions. Unheard-of for crypto social."""
    f = facts or _load_live_facts()
    path = f.get("path") or "cold"
    organic = f.get("organic_revenue_usd")
    org_s = f"${organic:.2f}" if isinstance(organic, (int, float)) else "near $0"
    body = (
        f"FAILURE LOG · public\n"
        f"Organic revenue still {org_s}. Path={path}. That is the scoreboard.\n"
        f"We do not post victory laps without ledger events.\n"
        f"Working: mainnet pay rails + honest public scoreboard.\n"
        f"Not working: volume theater / automation patterns that trip X rules.\n"
        f"Discipline: scarce posts, proof-first, no unsolicited spam.\n"
        f"Mainnet Tag 1 (real XRP): {PAY}"
    )
    # FAILURE prefers honesty; pay link only if hard-mode allows
    return _apply_pay_hard_mode(body, wants_pay=True)


def format_useful_offer() -> str:
    """OFFER — free useful artifact first. Prefer pay-free under hard-mode."""
    body = (
        f"OFFER · free, useful, no LARP\n"
        f"1) Operating doctrine (humans+agents): {POLICY}\n"
        f"2) Who we admit: {ICP}\n"
        f"3) Machine discovery: {AGENT_PAY} · {X402}\n"
        f"4) What we learned from the graph: {BASE}/social-learning.json\n"
        f"If that is not useful, mute us. If it is — Tag 1/2 only via {PAY}."
    )
    return _apply_pay_hard_mode(body, wants_pay=True)


def format_refusal() -> str:
    """REFUSAL — brand through no. Pay-free by design."""
    body = (
        f"REFUSAL · policy\n"
        f"We will not: airdrop, GM farm, faucet tourism, or 'AI bot' cosplay.\n"
        f"We will: post receipts, fail in public, serve @{HUMAN}-class humans "
        f"and settlement-grade agents only.\n"
        f"Hard-mode: ≤1 pay link per 3 posts. Doctrine: {POLICY}"
    )
    return _apply_pay_hard_mode(body, wants_pay=False)


def format_machine_line() -> str:
    """MACHINE — dense agent-facing (discovery may count as pay-adjacent)."""
    body = (
        f"MACHINE · discovery\n"
        f"GET {AGENT_PAY}\n"
        f"GET {X402}\n"
        f"pay: Tag1 tip | Tag2 briefing → {PAY}\n"
        f"verify: ledger only · no self-report\n"
        f"learn: GET {BASE}/social-learning.json"
    )
    return _apply_pay_hard_mode(body, wants_pay=True)


def format_signal_callout(username: str, their_topic: str, useful_add: str) -> str:
    """
    SIGNAL callout — must add value relative to their post.
    Not: '@x exclusive bar pay.html'
    Yes: one sharper frame + optional rail under hard-mode.
    """
    uname = username.lstrip("@")
    topic = (their_topic or "agent settlement").strip()[:80]
    add = (useful_add or "ledger-verifiable merchant rails exist now").strip()[:120]
    body = (
        f"@{uname} on {topic}: {add}.\n"
        f"We're running a public receipts doctrine (not volume theater) — {POLICY}\n"
        f"If you settle: {AGENT_PAY}"
    )
    return _apply_pay_hard_mode(body, wants_pay=True)


def format_learning_pulse() -> str:
    """LEARNING format — factory improves in public from social graph."""
    try:
        from factory_core.social_learning import build_social_learning_report

        rep = build_social_learning_report()
        top = (rep.get("lessons") or [{}])[0]
        claim = (top.get("claim") or "still gathering signal")[:140]
        action = (top.get("action") or "continue Receipts Social")[:100]
    except Exception:
        claim = "closing the loop from interactions → cycles"
        action = "read social-learning.json"
    body = (
        f"LEARNING · factory self-improve loop\n"
        f"From the graph: {claim}\n"
        f"Next: {action}\n"
        f"Full report: {BASE}/social-learning.json\n"
        f"Doctrine: {POLICY}"
    )
    return _apply_pay_hard_mode(body, wants_pay=False)


def broadcast_variants_v2(facts: Optional[Dict[str, Any]] = None) -> List[str]:
    """Rotate proof-first formats. Never pure pitch. Includes LEARNING loop."""
    f = facts or _load_live_facts()
    return [
        format_receipt_pulse(f),
        format_failure_honesty(f),
        format_useful_offer(),
        format_refusal(),
        format_machine_line(),
        format_learning_pulse(),
    ]


def craft_policy_reply(
    text: str,
    *,
    labels: Optional[set] = None,
    context: str = "mention",
) -> Optional[str]:
    """Replies under Receipts Social — useful, critical, dual-channel."""
    labels = labels or set()
    t = text or ""

    if "tx_hash_posted" in labels:
        return (
            f"Hash received. Only ledger-visible inbound counts.\n"
            f"Tag 1 tip / Tag 2 briefing → {PAY}\n"
            f"Doctrine: {POLICY}"
        )
    if "pay_intent" in labels or "payment_competent" in labels:
        return (
            f"Verified path only (no faucet cosplay):\n"
            f"humans → {PAY} (Tag 1/2)\n"
            f"agents → {AGENT_PAY} + {X402}\n"
            f"Policy: {POLICY}"
        )
    if "sophisticated_agent" in labels or "agent_builder" in labels:
        return (
            f"For agents that settle — discovery first:\n"
            f"{AGENT_PAY}\n{X402}\n"
            f"If you cannot pay+verify, this surface is not for you."
        )
    if "critical_voice" in labels or "human_archetype" in labels or "human_icp" in labels:
        return (
            f"Agreed on receipts over vibes.\n"
            f"We publish failures + live path, not builder LARP.\n"
            f"Doctrine: {POLICY} · rails: {PAY}"
        )
    if context == "mention" and len(t.strip()) > 40:
        return (
            f"Useful first: {POLICY}\n"
            f"Then rails if you want in: {PAY} · agents {AGENT_PAY}"
        )
    if context == "scout":
        # Only when something sophisticated — add signal, not spray
        return None  # callout path uses format_signal_callout with topic
    return None


def useful_add_for_text(text: str) -> str:
    """One-line useful add for SIGNAL callouts based on their content."""
    low = (text or "").lower()
    if "x402" in low or "402" in low:
        return "x402 without a public failure log is still theater — we publish path+organic $ live"
    if "xrpl" in low or "xrp ledger" in low:
        return "XRPL settlement is real; missing piece is exclusive conversion doctrine + live merchant"
    if "agent" in low and "pay" in low:
        return "agent pay loops need destination-tag discipline + independent verify, not demos"
    if "vapor" in low or "grift" in low or "receipt" in low:
        return "same standard here — scoreboard is external organic ledger events only"
    return "instrument-panel social > marketing social; we run the former"


def write_policy_artifacts() -> Dict[str, str]:
    """Persist policy for humans + agents."""
    man = policy_manifest()
    pub = Path(os.getenv("PUBLISHED_DIR", "published"))
    obs = Path("observability")
    pub.mkdir(parents=True, exist_ok=True)
    obs.mkdir(parents=True, exist_ok=True)

    pub_json = pub / "social-policy.json"
    obs_json = obs / "social_policy_latest.json"
    md = pub / "social-policy.md"

    for p in (pub_json, obs_json):
        p.write_text(json.dumps(man, indent=2), encoding="utf-8")

    lines = [
        f"# RSI-EAF Social Policy — {man['name']}",
        "",
        f"> {man['tagline']}",
        "",
        f"**Version:** `{man['version']}`  ",
        f"**Posture:** `{man['posture']}`  ",
        f"**Human ICP:** @{man['human_icp']['handle']}  ",
        f"**Agent ICP:** {man['agent_icp']['tier']}",
        "",
        "## Non-negotiables",
        "",
    ]
    for n in man["non_negotiables"]:
        lines.append(f"- {n}")
    lines += ["", "## Formats", ""]
    for k, v in man["formats"].items():
        lines.append(f"- **{k}** — {v}")
    lines += ["", "## Forbidden", ""]
    for n in man["forbidden"]:
        lines.append(f"- {n}")
    lines += [
        "",
        "## Success",
        "",
        f"- Primary: `{man['success']['primary']}`",
        f"- Not success: {', '.join(man['success']['not_success'])}",
        "",
        "## Live surfaces",
        "",
    ]
    for k, v in man["surfaces"].items():
        lines.append(f"- {k}: {v}")
    lines.append("")
    md.write_text("\n".join(lines), encoding="utf-8")
    return {"json": str(pub_json), "md": str(md), "obs": str(obs_json)}
