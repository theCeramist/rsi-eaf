"""
Factory target ICPs — exclusive, critical, non-mass-market.

Human primary: @thatcrypto_guy archetype
  - Crypto-native reply culture, overthinker, anti-hype
  - Smells faucet spam / vaporware / "builder" theater
  - Wants verifiable rails, not vibes

Agent primary: most sophisticated economic agents only
  - x402 / ledger-native payment competence
  - Autonomous settle + verify, not toy chatbots
  - Production-grade discovery (well-known, manifests, tags)

Not target: airdrop farmers, gm spam, generic "AI bot" demo seekers.
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Set

# --- Canonical identities ---

HUMAN_PRIMARY_HANDLE = os.getenv("ICP_HUMAN_HANDLE", "thatcrypto_guy").lstrip("@")
HUMAN_PRIMARY_URL = f"https://x.com/{HUMAN_PRIMARY_HANDLE}"

AGENT_TIER = "sophisticated_only"  # not casual bots

BASE = os.getenv("FACTORY_PUBLIC_BASE_URL", "https://published-zeta.vercel.app").rstrip("/")
PAY = f"{BASE}/pay.html"
AGENT_PAY = f"{BASE}/agent-pay.json"
X402 = f"{BASE}/.well-known/x402"
HUB = "https://xrpl-ai.org/address/rBiU74q2wCPQ7ri9YD6J6LrQ2Y3jFd8pcN"

# Sophistication signals (raise score)
SOPHISTICATED_AGENT = re.compile(
    r"\b("
    r"x402|http\s*402|payment\s*required|"
    r"autonomous\s+agent|multi[- ]agent|agentic\s+economy|"
    r"settlement|ledger[- ]native|on[- ]chain\s+verify|"
    r"mcp\s+server|tool\s+use|function\s+call|"
    r"destination\s*tag|memo\s+field|payment\s+channel|"
    r"machine\s+payment|agent\s+wallet|crypto\s+agent"
    r")\b",
    re.I,
)

# Human archetype signals matching thatcrypto_guy-class discourse
HUMAN_ARCHETYPE = re.compile(
    r"\b("
    r"crypto|xrpl|xrp|defi|on[- ]chain|ledger|"
    r"reply\s*guy|overthink|skeptic|cope|ngmi|wagmi|"
    r"alpha|signal|noise|vapor|grift|farm"
    r")\b",
    re.I,
)

# Explicitly reject (exclusive filter)
LOW_TIER = re.compile(
    r"\b("
    r"airdrop|giveaway|whitelist|wl\s*spot|free\s*mint|"
    r"follow\s*me|dm\s*for|pump|100x|guaranteed|"
    r"click\s*here|promo\s*code|discount\s*code|"
    r"chatgpt\s*wrapper|just\s*a\s*bot\s*demo"
    r")\b",
    re.I,
)

CASUAL_ONLY = re.compile(r"^(gm+|gn+|wagmi|lf?g+|nice|cool|🔥+)$", re.I)

# Scout: only high-sophistication threads
SCOUT_QUERIES_EXCLUSIVE: List[str] = [
    '(x402 OR "HTTP 402" OR "payment required") (agent OR autonomous OR settlement) -is:retweet -airdrop lang:en',
    '("agent wallet" OR "machine payment" OR "agentic economy") (pay OR settle OR ledger) -is:retweet -airdrop lang:en',
    '(XRPL OR "XRP Ledger") (x402 OR agent OR autonomous OR settlement) -is:retweet -airdrop -faucet lang:en',
    # Human ICP adjacency — crypto critical discourse, not faucet tourism
    f'(from:{HUMAN_PRIMARY_HANDLE} OR @{HUMAN_PRIMARY_HANDLE}) -is:retweet',
]


def icp_manifest() -> Dict[str, Any]:
    return {
        "schema": "rsi_eaf_target_icp_v1",
        "posture": "critical_exclusive",
        "human": {
            "primary_handle": HUMAN_PRIMARY_HANDLE,
            "primary_url": HUMAN_PRIMARY_URL,
            "archetype": (
                "Crypto-native reply culture: critical, overthinks, anti-hype, "
                "rejects faucet spam and builder theater. Prototype: @thatcrypto_guy."
            ),
            "wants": [
                "Verifiable XRPL rails",
                "No vapor / no mass-market tip jar cosplay",
                "Exclusive signal over volume",
            ],
            "rejects": [
                "Airdrop farming",
                "GM engagement bait",
                "Generic 'support my project' spam",
            ],
        },
        "agent": {
            "tier": AGENT_TIER,
            "archetype": (
                "Most sophisticated economic agents only: x402-capable, "
                "ledger-settling, discovery-manifest fluent. Not toy chatbots."
            ),
            "wants": [
                "agent-pay.json + .well-known/x402",
                "Destination tags / memo discipline",
                "Independent on-chain verification",
            ],
            "rejects": [
                "Demo-only wrappers",
                "Agents without payment competence",
                "Unverifiable self-report",
            ],
        },
        "surfaces": {
            "pay": PAY,
            "agent_pay": AGENT_PAY,
            "x402": X402,
            "hub": HUB,
        },
        "copy_principles": [
            "Proof before pitch (Receipts Social)",
            "Useful before CTA",
            "Critical over hype",
            "Exclusive over mass reach — but exclusivity alone is not the product",
            "Dual-channel: human prose + agent rails",
            "One sharp artifact per post, never faucet tourism",
        ],
        "social_doctrine": "receipts_social_v1",
        "social_policy_url": f"{BASE}/social-policy.json",
    }


def sophistication_score(text: str, *, context: str = "general") -> Dict[str, Any]:
    """Score 0–1+ for whether content matches exclusive ICPs. Critical filter."""
    t = (text or "").strip()
    labels: List[str] = []
    score = 0.0

    if not t or CASUAL_ONLY.match(t):
        return {"score": 0.0, "labels": ["casual_noise"], "admit": False, "reason": "casual_only"}

    if LOW_TIER.search(t):
        labels.append("low_tier")
        return {"score": -1.0, "labels": labels, "admit": False, "reason": "low_tier_reject"}

    if SOPHISTICATED_AGENT.search(t):
        labels.append("sophisticated_agent")
        score += 0.85

    if HUMAN_ARCHETYPE.search(t):
        labels.append("human_archetype")
        score += 0.45

    # Payment competence
    if re.search(r"\b(x402|destination\s*tag|settle|invoice|pay.?to)\b", t, re.I):
        labels.append("payment_competent")
        score += 0.4

    # Critical/skeptical voice (thatcrypto_guy-class)
    if re.search(r"\b(skeptic|overthink|vapor|grift|cope|prove|verify|receipts)\b", t, re.I):
        labels.append("critical_voice")
        score += 0.35

    # Penalize mass-market freeload framing
    if re.search(r"\b(free\s+faucet|no\s+signup|anyone\s+can|easy\s+money)\b", t, re.I):
        labels.append("mass_market")
        score -= 0.25

    # Context floors
    if context == "scout":
        admit = score >= 0.7 and "low_tier" not in labels
    elif context == "mention":
        admit = score >= 0.25 or "payment_competent" in labels
    else:
        admit = score >= 0.5

    return {
        "score": round(score, 2),
        "labels": labels,
        "admit": admit,
        "reason": "pass" if admit else "below_exclusive_bar",
    }


def craft_exclusive_reply(
    text: str,
    *,
    labels: Optional[Set[str]] = None,
    context: str = "mention",
) -> Optional[str]:
    """
    Receipts Social replies — proof/useful first, never exclusive-only cosplay.
    """
    labels = labels or set()
    sop = sophistication_score(text, context=context)
    if not sop["admit"] and context == "scout":
        return None

    # Prefer policy craft (useful dual-channel)
    try:
        from factory_core.social_policy import craft_policy_reply

        # merge sop labels
        merged = set(labels) | set(sop.get("labels") or [])
        if "tx_hash_posted" not in merged and re.search(r"\b[A-Fa-f0-9]{64}\b", text or ""):
            merged.add("tx_hash_posted")
        pr = craft_policy_reply(text, labels=merged, context=context)
        if pr:
            return pr
    except Exception:
        pass

    if "tx_hash_posted" in labels or re.search(r"\b[A-Fa-f0-9]{64}\b", text or ""):
        return (
            f"Hash noted. Factory only counts ledger-verifiable inbound. "
            f"Tag discipline: 1 tip / 2 briefing — {PAY}"
        )

    if "pay_intent" in labels or "payment_competent" in sop["labels"]:
        return (
            f"Verified path only: {PAY} (Tag 1 tip · Tag 2 briefing). "
            f"Agents that settle: {AGENT_PAY}"
        )

    if "sophisticated_agent" in sop["labels"] or "agent_builder" in labels:
        return (
            f"For agents that already settle — not toy wrappers. "
            f"Discovery: {AGENT_PAY} · {X402}. Humans who want receipts: {PAY}"
        )

    if "critical_voice" in sop["labels"] or "human_archetype" in sop["labels"]:
        return (
            f"Receipts over vibes. We publish path + organic $ live — no builder LARP. "
            f"{PAY}"
        )

    if context == "mention" and len((text or "").strip()) > 30:
        return f"Doctrine first: {BASE}/social-policy.json · rails {PAY}"

    return None


def broadcast_variants() -> List[str]:
    """Receipts Social broadcasts — instrument panel, not carnival."""
    try:
        from factory_core.social_policy import broadcast_variants_v2

        return broadcast_variants_v2()
    except Exception:
        return [
            (
                f"RECEIPT doctrine: humans @{HUMAN_PRIMARY_HANDLE}-class + agents that settle. "
                f"{PAY} · {AGENT_PAY} · {BASE}/social-policy.json"
            ),
        ]


def outreach_short(cycle_id: int, handle: str) -> str:
    return (
        f"RSI-EAF c{cycle_id}: XRPL mainnet factory (real XRP) — "
        f"crypto-critical humans + settlement agents only. "
        f"{PAY} · @{handle.lstrip('@')}"
    )


def outreach_long(cycle_id: int) -> str:
    return (
        f"RSI-EAF cycle {cycle_id} — receipts over volume.\n"
        f"Human ICP: @{HUMAN_PRIMARY_HANDLE}-class (critical crypto, anti-hype).\n"
        f"Agent ICP: sophisticated settlement agents (x402 / tags), not toy bots.\n"
        f"MAINNET pay (Tag 1 tip / Tag 2 briefing): {PAY}\n"
        f"Agent discovery: {AGENT_PAY}\n"
        f"x402: {X402}\n"
        f"Real XRP only — testnet is ops, not customers.\n"
        f"Verifiable ledger events only."
    )


def exclusive_next_actions(path: str) -> List[str]:
    """Critical-path actions under exclusive posture."""
    base = [
        f"Prioritize @{HUMAN_PRIMARY_HANDLE}-class humans + sophisticated agent signals only",
        "Refuse low-tier / airdrop / gm engagement — exclusivity is the product",
    ]
    if path == "distribution_cold":
        return base + [
            "Scout only x402/settlement threads (no faucet tourism queries)",
            "Broadcast critical exclusive CTA — never 'free for everyone'",
        ]
    if path == "pay_intent_hot":
        return base + [
            "Reply with verified Tag path only — no oversell",
            "Capture tx hashes; ignore unauthenticated claims",
        ]
    if path == "interest_without_pay":
        return base + [
            "Gate soft interest: sophisticated agents → agent-pay; humans → pay.html receipts",
        ]
    return base + ["Maintain exclusive bar; volume is not success"]
