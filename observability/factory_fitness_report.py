"""
Factory fitness report — actions, inputs, outputs, evolution vs Agents.md primary goal.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from factory_core.mainnet_readiness import evaluate_mainnet_readiness
from factory_core.revenue_fitness import evaluate_revenue_models
from factory_core.self_improver import analyze_gate_trends, analyze_improvement_history
from gates.verifier import count_verified_revenue_events
from observability.economic_ledger import ledger


def _score_primary_goal(net: Dict[str, Any], verified: int) -> float:
    """0-100 vs Agents.md: positive net economic activity with verifiable revenue."""
    organic = float(net.get("organic_revenue_usd_est", 0))
    net_usd = float(net.get("net_usd_est", 0))
    if organic > 0 and net_usd >= 0:
        return 100.0
    if verified > 0 and organic > 0:
        return 60.0
    if verified > 0:
        return 35.0
    if net_usd >= 0:
        return 20.0
    return max(0.0, min(15.0, 15.0 + net_usd / 20.0))


def generate_factory_fitness_report(
    cycle_id: int = 0,
    *,
    persist_path: str = "observability/factory_fitness_report.json",
) -> Dict[str, Any]:
    net = ledger.calculate_net()
    verified = count_verified_revenue_events()
    fitness_models = evaluate_revenue_models()
    gates = analyze_gate_trends(limit_cycles=20)
    meta = analyze_improvement_history()
    mainnet = evaluate_mainnet_readiness()

    primary_score = _score_primary_goal(net, verified)

    report: Dict[str, Any] = {
        "schema": "rsi_eaf_factory_fitness_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cycle_id": cycle_id,
        "primary_goal": "positive_net_economic_activity_verifiable_revenue",
        "composite_score": round(primary_score, 1),
        "verdict": "passing" if primary_score >= 60 else "failing",
        "economics": {**net, "verified_revenue_events": verified},
        "actions": {
            "inputs": [
                "Grok session tokens (cost)",
                "XRPL testnet faucet XRP",
                "Vercel/GitHub API",
                "Factory .env secrets",
                "External payer XRP (missing)",
            ],
            "outputs": [
                "published/*.html assets",
                "XRPL outbound anchor txs",
                "nexus_data.json on jarvis-swarm",
                "economic_ledger.jsonl milestones",
                "verified revenue events (0 today)",
            ],
            "evolution": {
                "stale_proposals": meta.get("stale_proposals", [])[:5],
                "gate_pass_rate": gates.get("pass_rate"),
                "top_gate_failures": gates.get("top_failures"),
                "implemented_proposals": meta.get("implemented_count"),
            },
        },
        "revenue_model_fitness": {
            "top3": fitness_models.get("top3_ids"),
            "ranked": [
                {"id": m["id"], "fitness": m["fitness"], "notes": m.get("notes", "")[:120]}
                for m in fitness_models.get("ranked", [])[:6]
            ],
        },
        "strengths": [
            "Autonomous hybrid cycling with 6 revenue engines",
            "XRPL outbound anchoring per publish",
            "Live Vercel + aetherforge nexus sync",
            "Treasury daemons + ingest pipeline (idle until external payers)",
        ],
        "critical_gaps": [
            "Zero verified organic revenue in ledger",
            "Publish loop ≠ revenue loop (engines log $0 anchors)",
            "Evolution optimizes surfaces not monetization",
            f"Cumulative net ${net.get('net_usd_est')} with $0 organic",
        ],
        "mainnet": mainnet,
        "recommendations": [
            "Share agent-pay.json URL with paying agents (Destination Tag 1)",
            "Enable REVENUE_INGEST_SMOKE_TEST with TEST_SUPPORTER_SEED",
            "Do not enable mainnet until mainnet.ready_for_mainnet is true",
            "Archive jarvis-swarm-memory scheduled workflows (rsi-eaf is SSOT)",
        ],
    }

    path = Path(persist_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report