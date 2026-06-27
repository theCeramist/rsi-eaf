"""
Cycle analysis — structured performance report from ledger + execution data.
"""

from typing import Any, Dict, List

from observability.economic_ledger import ledger


def analyze_cycle(
    cycle_id: int,
    execution_result: Dict[str, Any],
    xrpl_balance: float,
    gate_result: Dict[str, Any],
) -> Dict[str, Any]:
    net_cycle = ledger.calculate_net(since_cycle=cycle_id)
    net_all = ledger.calculate_net()
    events = [e for e in ledger.get_recent_events(500) if e.get("cycle_id") == cycle_id]

    costs = sum(float(e.get("amount_usd_est", 0)) for e in events if e.get("event_type") == "cost")
    revenue = sum(float(e.get("amount_usd_est", 0)) for e in events if e.get("event_type") == "revenue")
    publish_types = {"asset_published", "tip_funnel_published", "briefing_published"}
    assets = sum(1 for e in events if e.get("event_type") in publish_types)

    recommendations: List[str] = []
    if revenue <= 0:
        recommendations.append("Activate supporter tipping on live published pages (treasury + revenue memo).")
    if costs > 0 and revenue < costs:
        recommendations.append(f"Revenue/cost ratio {revenue/max(costs,0.01):.2f} — prioritize monetization before scaling cycles.")
    if not execution_result.get("live_url"):
        recommendations.append("Configure VERCEL_DEPLOY or FACTORY_PUBLIC_BASE_URL for live asset URLs.")
    elif not execution_result.get("live_verified"):
        recommendations.append("Live URL configured but unreachable — verify Vercel deploy and FACTORY_PUBLIC_BASE_URL.")
    if execution_result.get("treasury_ws_observed", 0) == 0 and revenue <= 0:
        recommendations.append(
            "No treasury inflows yet — share live asset URL and treasury address for testnet revenue memos."
        )
    if not gate_result.get("all_passed"):
        failed = [g["gate"] for g in gate_result.get("gates", []) if not g.get("passed")]
        recommendations.append(f"Fix failing gates: {', '.join(failed)}")

    return {
        "cycle_id": cycle_id,
        "net_this_cycle": net_cycle,
        "net_cumulative": net_all,
        "cycle_costs_usd": round(costs, 4),
        "cycle_revenue_usd": round(revenue, 4),
        "assets_published": assets,
        "xrpl_balance": xrpl_balance,
        "gates_passed": gate_result.get("all_passed", False),
        "verified_revenue_events": execution_result.get("verified_revenue_events", 0),
        "live_url": execution_result.get("live_url"),
        "bottlenecks": [
            b for b in [
                "no_verified_revenue" if revenue <= 0 else None,
                "negative_unit_economics" if costs > revenue else None,
                "gates_failed" if not gate_result.get("all_passed") else None,
            ]
            if b
        ],
        "recommendations": recommendations,
    }