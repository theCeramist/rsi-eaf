"""
Revenue model fitness scoring for RSI-EAF (AGENTS.md grounded economics).
"""

from __future__ import annotations

from typing import Any, Dict, List

# Weights sum to 1.0 — verifiable near-term revenue dominates.
_WEIGHTS = {
    "xrpl_verifiable": 0.25,
    "near_term_revenue": 0.25,
    "factory_readiness": 0.20,
    "low_risk": 0.15,
    "flywheel": 0.15,
}

_MODELS: List[Dict[str, Any]] = [
    {
        "id": "tokenized_equity",
        "name": "Tokenized Swarm Equity & Internal Capital Markets",
        "scores": {
            "xrpl_verifiable": 0.7,
            "near_term_revenue": 0.2,
            "factory_readiness": 0.4,
            "low_risk": 0.35,
            "flywheel": 0.85,
        },
        "notes": "Strong flywheel; needs trust lines/issued currency — gated post mainnet proof.",
    },
    {
        "id": "prediction_alpha",
        "name": "Autonomous Prediction & Alpha Syndicate",
        "scores": {
            "xrpl_verifiable": 0.35,
            "near_term_revenue": 0.25,
            "factory_readiness": 0.3,
            "low_risk": 0.25,
            "flywheel": 0.6,
        },
        "notes": "Regulatory/position risk; extends paid_briefing but not cycle-1 ready.",
    },
    {
        "id": "micro_saas",
        "name": "Self-Building Micro-SaaS / Tool Factory",
        "scores": {
            "xrpl_verifiable": 0.95,
            "near_term_revenue": 0.9,
            "factory_readiness": 0.95,
            "low_risk": 0.85,
            "flywheel": 0.9,
        },
        "notes": "Core factory identity — Vercel publish + treasury already wired.",
    },
    {
        "id": "mythos_commerce",
        "name": "Narrative Commerce & Mythos Economy",
        "scores": {
            "xrpl_verifiable": 0.85,
            "near_term_revenue": 0.75,
            "factory_readiness": 0.8,
            "low_risk": 0.7,
            "flywheel": 0.8,
        },
        "notes": "aetherforge nexus + cycle artifacts drive tip conversion.",
    },
    {
        "id": "agent_marketplace",
        "name": "Agent-to-Agent Service Marketplace",
        "scores": {
            "xrpl_verifiable": 0.8,
            "near_term_revenue": 0.65,
            "factory_readiness": 0.75,
            "low_risk": 0.65,
            "flywheel": 0.75,
        },
        "notes": "tip-manifest + ACP; X402 later. Agent-readable catalog now.",
    },
    {
        "id": "yield_stewardship",
        "name": "Yield, Liquidity & On-Chain Capital Stewardship",
        "scores": {
            "xrpl_verifiable": 0.5,
            "near_term_revenue": 0.15,
            "factory_readiness": 0.2,
            "low_risk": 0.2,
            "flywheel": 0.55,
        },
        "notes": "Mainnet DeFi gated; testnet treasury too small for yield.",
    },
]


def _fitness(scores: Dict[str, float]) -> float:
    return round(sum(scores[k] * _WEIGHTS[k] for k in _WEIGHTS) * 100, 1)


def evaluate_revenue_models() -> Dict[str, Any]:
    """Rank all six models; return top 3 by composite fitness."""
    ranked = []
    for model in _MODELS:
        fitness = _fitness(model["scores"])
        ranked.append({**model, "fitness": fitness})
    ranked.sort(key=lambda m: m["fitness"], reverse=True)
    top3 = ranked[:3]
    return {
        "weights": _WEIGHTS,
        "ranked": ranked,
        "top3": top3,
        "top3_ids": [m["id"] for m in top3],
        "implementation": {
            "micro_saas": "revenue_engines.micro_saas_factory",
            "mythos_commerce": "revenue_engines.mythos_commerce",
            "agent_marketplace": "revenue_engines.agent_marketplace",
        },
        "deferred_roadmap": {
            "tokenized_equity": "XRPL trust lines + issued currency after mainnet proof cycles",
            "prediction_alpha": "Paid briefing extension + sandboxed prediction markets post-regulatory review",
            "yield_stewardship": "Treasury yield agents gated on mainnet + policy engine",
        },
    }