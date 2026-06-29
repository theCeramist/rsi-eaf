"""
Mainnet transition readiness — gated per Agents.md (testnet proof cycles first).
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

from gates.verifier import count_verified_revenue_events
from observability.economic_ledger import ledger


def evaluate_mainnet_readiness(
    *,
    min_verified_revenue_events: int = 3,
    min_positive_organic_cycles: int = 5,
    min_gate_pass_rate: float = 0.85,
) -> Dict[str, Any]:
    """
    Research-backed checklist before moving treasury to XRPL mainnet for REAL value.

    Agents.md requires multiple successful economic cycles on testnet first.
    """
    net = ledger.calculate_net()
    verified = count_verified_revenue_events()
    organic = float(net.get("organic_revenue_usd_est", 0))
    costs = float(net.get("total_cost_usd_est", 0))

    blockers: List[str] = []
    warnings: List[str] = []

    if verified < min_verified_revenue_events:
        blockers.append(
            f"verified_revenue_events {verified} < {min_verified_revenue_events} "
            "(prove ingest on testnet first)"
        )
    if organic <= 0:
        blockers.append("organic_revenue_usd_est is zero — no proven payer conversion")
    if net.get("net_usd_est", 0) < 0:
        warnings.append(f"net still negative (${net.get('net_usd_est'):.2f}) — mainnet amplifies loss risk")

    seed_ok = bool(os.getenv("FACTORY_XRPL_SEED", "").strip())
    treasury_ok = bool(os.getenv("FACTORY_TREASURY_ADDRESS", "").strip())
    if not seed_ok:
        blockers.append("FACTORY_XRPL_SEED not configured for controlled mainnet wallet")
    if not treasury_ok:
        warnings.append("FACTORY_TREASURY_ADDRESS unset — will default to factory wallet")

    smoke = os.getenv("REVENUE_INGEST_SMOKE_TEST", "false").lower() in {"1", "true", "yes"}
    if not smoke and verified == 0:
        warnings.append("Enable REVENUE_INGEST_SMOKE_TEST to validate pipeline before mainnet")

    try:
        from factory_core.self_improver import analyze_gate_trends

        trends = analyze_gate_trends(limit_cycles=20)
        if trends.get("pass_rate", 0) < min_gate_pass_rate:
            warnings.append(
                f"gate pass_rate {trends.get('pass_rate')} < {min_gate_pass_rate}"
            )
    except Exception:
        trends = {}

    ready = len(blockers) == 0
    return {
        "ready_for_mainnet": ready,
        "blockers": blockers,
        "warnings": warnings,
        "metrics": {
            "verified_revenue_events": verified,
            "organic_revenue_usd_est": organic,
            "total_cost_usd_est": costs,
            "net_usd_est": net.get("net_usd_est"),
            "gate_trends": trends,
        },
        "transition_steps": [
            "1. Achieve 3+ verified organic inbound payments on testnet (tag 1 or agent-pay.json)",
            "2. Set XRPL_NETWORK=mainnet and XRPL_MAINNET_URL in .env (never commit seeds)",
            "3. Fund mainnet treasury with controlled XRP reserve (MIN_XRP_RESERVE)",
            "4. Update agent-pay.json network field + republish surfaces",
            "5. Run one mainnet smoke payment; confirm ledger verified: true",
            "6. Enable mainnet only when net_usd_est >= 0 for N consecutive cycles",
        ],
        "revenue_fit_on_mainnet": {
            "micro_saas": "Highest fit — agent-pay Tag 3, real unlock USD",
            "agent_marketplace": "Strong — Tag 4 service catalog, agent-to-agent",
            "mythos_commerce": "Moderate — narrative tips via aetherforge CTA",
            "deferred": ["yield_stewardship", "tokenized_equity", "prediction_alpha"],
        },
        "why_mainnet_now_or_not": (
            "Mainnet unlocks REAL economic grounding per Agents.md, but the factory has "
            f"{verified} verified revenue events and ${organic:.2f} organic after "
            f"${costs:.2f} costs. Transition before testnet proof repeats publish-without-capture "
            "on real money."
        ),
    }