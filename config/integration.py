"""
Unified integration contract — GitHub, Vercel, jarvis-swarm / aetherforge, XRPL.

All factory modules import targets and URLs from here instead of hardcoding.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

# --- GitHub: factory distribution (rsi-eaf) ---
GITHUB_OWNER = os.getenv("GITHUB_DISTRIBUTION_OWNER", "theCeramist")
GITHUB_REPO = os.getenv("GITHUB_DISTRIBUTION_REPO", "rsi-eaf")
GITHUB_BRANCH = os.getenv("GITHUB_DISTRIBUTION_BRANCH", "main")
GITHUB_REPO_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}"
GITHUB_SUPPORT_ISSUE = int(os.getenv("GITHUB_SUPPORT_ISSUE", "1"))
GITHUB_CI_WORKFLOW = os.getenv("GITHUB_CI_WORKFLOW", "Factory CI")

# --- GitHub: nexus / aetherforge (jarvis-swarm) ---
NEXUS_OWNER = os.getenv("NEXUS_GITHUB_OWNER", os.getenv("NEXUS_CI_GATE_OWNER", "theCeramist"))
NEXUS_REPO = os.getenv("NEXUS_GITHUB_REPO", os.getenv("NEXUS_CI_GATE_REPO", "jarvis-swarm"))
NEXUS_BRANCH = os.getenv("NEXUS_GITHUB_BRANCH", "main")
NEXUS_REPO_URL = f"https://github.com/{NEXUS_OWNER}/{NEXUS_REPO}"
NEXUS_CI_HYGIENE_GATE = os.getenv("NEXUS_CI_HYGIENE_GATE", "true").lower() in {"1", "true", "yes"}
JARVIS_CI_AUTO_REPAIR = os.getenv("JARVIS_CI_AUTO_REPAIR", "true").lower() in {"1", "true", "yes"}

# --- Vercel: factory static site ---
FACTORY_PUBLIC_BASE_URL = os.getenv(
    "FACTORY_PUBLIC_BASE_URL", "https://published-zeta.vercel.app"
).rstrip("/")
AETHERFORGE_URL = os.getenv("AETHERFORGE_URL", "https://aetherforge.world").rstrip("/")
PUBLISHED_DIR = os.getenv("PUBLISHED_DIR", "published")
VERCEL_DEPLOY_COOLDOWN_MINUTES = int(os.getenv("VERCEL_DEPLOY_COOLDOWN_MINUTES", "20"))
PUBLISHED_DEPLOY_MAX_HTML = int(os.getenv("PUBLISHED_DEPLOY_MAX_HTML", "12"))

# --- Cadence ---
DISTRIBUTION_EVERY_N_CYCLES = int(os.getenv("DISTRIBUTION_EVERY_N_CYCLES", "3"))
GIST_PUBLISH_EVERY_N_CYCLES = int(os.getenv("GIST_PUBLISH_EVERY_N_CYCLES", "3"))
GITHUB_RELEASE_EVERY_N_CYCLES = int(os.getenv("GITHUB_RELEASE_EVERY_N_CYCLES", "5"))
NEXUS_EMIT_EVERY_N_CYCLES = int(os.getenv("NEXUS_EMIT_EVERY_N_CYCLES", "1"))

# --- XRPL ---
XRPL_TESTNET_EXPLORER = "https://testnet.xrpl.org/"
XRPL_TESTNET_WS = os.getenv("XRPL_TESTNET_WS", "wss://s.altnet.rippletest.net:51233")

# --- Revenue engines ---
REVENUE_TOP3_ENABLED = os.getenv("REVENUE_TOP3_ENABLED", "true").lower() in {"1", "true", "yes"}

# --- Control-state goals (jarvis / aetherforge alignment) ---
THE_FOUR_CONTROL_STATE_GOALS = [
    "Improve coordination, outcome evaluation, and learning between parallel sub-agents",
    "Enhance observability and GitNexus persistence of autonomous subagent runs",
    "Evolve stronger human-swarm symbiosis surface in response to recent Nexus interaction",
    "Strengthen self-sufficiency monitoring, bottleneck detection, and autonomous pause/resume logic",
]

ASI_TIER_1 = (
    "Real intelligence traces + mandatory external Vercel/Nexus feedback on live "
    "aetherforge.world / jarvis-swarm / rsi-eaf. "
    "RSI-EAF factory cycles anchored on XRPL with verifiable revenue surfaces."
)


def github_targets() -> Dict[str, Any]:
    return {
        "factory": {"owner": GITHUB_OWNER, "repo": GITHUB_REPO, "branch": GITHUB_BRANCH, "url": GITHUB_REPO_URL},
        "nexus": {"owner": NEXUS_OWNER, "repo": NEXUS_REPO, "branch": NEXUS_BRANCH, "url": NEXUS_REPO_URL},
    }


def vercel_targets() -> Dict[str, str]:
    return {
        "factory_site": FACTORY_PUBLIC_BASE_URL,
        "aetherforge": AETHERFORGE_URL,
        "published_dir": PUBLISHED_DIR,
    }


def revenue_surface_rows(featured: Dict[str, str], cycle_id: int) -> List[Tuple[str, str]]:
    """Canonical revenue surface table rows for docs + nexus."""
    base = FACTORY_PUBLIC_BASE_URL
    rows: List[Tuple[str, str]] = [
        ("Factory index", f"{base}/" if base else "n/a"),
        ("Tip page", featured.get("canonical_tip_page") or featured.get("tip_page", "")),
        ("Agent tip manifest", featured.get("tip_manifest") or (f"{base}/tip-manifest.json" if base else "")),
        ("Paid briefing", featured.get("briefing_page", "")),
    ]
    if featured.get("mythos_page"):
        rows.append(("Mythos artifact (Tag 5)", featured["mythos_page"]))
    if featured.get("micro_tool_page"):
        rows.append(("Micro-tool (Tag 3)", featured["micro_tool_page"]))
    if featured.get("service_catalog"):
        rows.append(("Agent service catalog (Tag 4)", featured["service_catalog"]))
    rows.append(("aetherforge nexus", AETHERFORGE_URL))
    rows.append(("jarvis-swarm repo", NEXUS_REPO_URL))
    return [(label, url) for label, url in rows if url]


def integration_manifest(cycle_id: int = 0, featured: Dict[str, str] | None = None) -> Dict[str, Any]:
    """Compact additive merge of all agentic-AI integration endpoints for nexus + health."""
    featured = featured or {}
    from factory_core.revenue_fitness import evaluate_revenue_models

    fitness = evaluate_revenue_models()
    return {
        "schema": "rsi_eaf_integration_v1",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "cycle_id": cycle_id,
        "github": github_targets(),
        "vercel": vercel_targets(),
        "xrpl": {"network": "testnet", "explorer": XRPL_TESTNET_EXPLORER, "ws": XRPL_TESTNET_WS},
        "revenue_surfaces": revenue_surface_rows(featured, cycle_id),
        "revenue_engines": {
            "top3_enabled": REVENUE_TOP3_ENABLED,
            "top3_ids": fitness.get("top3_ids", []),
            "implementation": fitness.get("implementation", {}),
            "deferred": [m["id"] for m in fitness.get("ranked", []) if m["id"] not in fitness.get("top3_ids", [])],
        },
        "cadence": {
            "distribution_every_n": DISTRIBUTION_EVERY_N_CYCLES,
            "nexus_emit_every_n": NEXUS_EMIT_EVERY_N_CYCLES,
            "vercel_cooldown_min": VERCEL_DEPLOY_COOLDOWN_MINUTES,
        },
        "gates": {
            "github_ci": GITHUB_CI_WORKFLOW,
            "nexus_ci_hygiene": NEXUS_CI_HYGIENE_GATE,
            "jarvis_ci_auto_repair": JARVIS_CI_AUTO_REPAIR,
        },
        "control_state_goals": THE_FOUR_CONTROL_STATE_GOALS,
        "asi_tier_1": ASI_TIER_1,
        "external_links": {
            "aetherforge": AETHERFORGE_URL,
            "factory_vercel": FACTORY_PUBLIC_BASE_URL,
            "github_rsi_eaf": GITHUB_REPO_URL,
            "github_jarvis_swarm": NEXUS_REPO_URL,
        },
    }