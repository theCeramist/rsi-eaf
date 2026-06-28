"""
Recursive self-improvement — meta-analysis of tool logs, proposals, gates, ledger.
Balances revenue pursuit with tool hardening and RSI meta-cycles.
"""

import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from factory_core.stale_evolution import BUILTIN_IMPLEMENTED, filter_stale_proposals
from factory_core.state import FactoryState
from observability.economic_ledger import ledger

IMPROVEMENTS_LOG = Path(os.getenv("TOOL_IMPROVEMENTS_LOG", "factory_core/tool_improvements.jsonl"))
PROPOSALS_DIR = Path(os.getenv("FACTORY_PROPOSALS_DIR", "factory_core/proposals"))
RSI_LOG = Path(os.getenv("RSI_IMPROVEMENTS_LOG", "factory_core/rsi_improvements.jsonl"))
REVENUE_TARGET_USD = float(os.getenv("REVENUE_TARGET_USD", "10.0"))
FOCUS_ROTATION = ["revenue", "tools", "rsi"]


def _append_rsi_log(entry: Dict[str, Any]) -> None:
    RSI_LOG.parent.mkdir(parents=True, exist_ok=True)
    with RSI_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")


def _read_jsonl(path: Path, limit: int = 100) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    entries = []
    for line in lines[-limit:]:
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def load_tool_improvement_entries(limit: int = 50) -> List[Dict[str, Any]]:
    return _read_jsonl(IMPROVEMENTS_LOG, limit)


def load_proposal_history(limit: int = 30) -> List[Dict[str, Any]]:
    proposals = []
    if not PROPOSALS_DIR.exists():
        return proposals
    files = sorted(PROPOSALS_DIR.glob("cycle-*.json"), key=lambda p: p.stat().st_mtime)[-limit:]
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                proposals.append({"file": str(path), "proposals": data})
            elif isinstance(data, dict) and "proposals" in data:
                proposals.append({"file": str(path), **data})
        except (json.JSONDecodeError, OSError):
            continue
    return proposals


def analyze_gate_trends(limit_cycles: int = 20) -> Dict[str, Any]:
    """Scan recent cycle completion milestones for gate pass/fail patterns."""
    events = ledger.get_recent_events(limit=500)
    completions = [
        e for e in events
        if e.get("source") == "cycle_runner"
        and e.get("metadata", {}).get("phase") == "complete"
    ][-limit_cycles:]

    pass_count = 0
    fail_gates: Counter = Counter()
    for event in completions:
        gates = event.get("metadata", {}).get("gates", {})
        if gates.get("all_passed"):
            pass_count += 1
        else:
            for g in gates.get("gates", []):
                if not g.get("passed"):
                    fail_gates[g.get("gate", "unknown")] += 1

    total = len(completions)
    return {
        "cycles_sampled": total,
        "pass_rate": round(pass_count / total, 3) if total else 0.0,
        "top_failures": fail_gates.most_common(5),
    }


def analyze_ledger_trends() -> Dict[str, Any]:
    net = ledger.calculate_net()
    recent = ledger.get_recent_events(limit=200)
    revenue_events = [e for e in recent if e.get("event_type") == "revenue"]
    cost_events = [e for e in recent if e.get("event_type") == "cost"]
    organic_gap = max(0.0, REVENUE_TARGET_USD - net.get("organic_revenue_usd_est", 0))
    return {
        "cumulative_net": net,
        "revenue_gap_usd": max(0.0, REVENUE_TARGET_USD - net.get("total_revenue_usd_est", 0)),
        "organic_revenue_gap_usd": organic_gap,
        "recent_revenue_count": len(revenue_events),
        "recent_cost_count": len(cost_events),
        "revenue_per_cost": round(
            net.get("total_revenue_usd_est", 0) / max(net.get("total_cost_usd_est", 0.01), 0.01),
            4,
        ),
        "organic_revenue_per_cost": round(
            net.get("organic_revenue_usd_est", 0) / max(net.get("total_cost_usd_est", 0.01), 0.01),
            4,
        ),
    }


def analyze_improvement_history() -> Dict[str, Any]:
    """Meta-analysis across tool_improvements.jsonl and proposal files."""
    tool_entries = load_tool_improvement_entries(limit=80)
    pytest_runs = [e for e in tool_entries if "pytest" in e]
    xrpl_runs = [e for e in tool_entries if "xrpl" in e]

    pytest_pass_rate = 0.0
    if pytest_runs:
        pytest_pass_rate = sum(1 for e in pytest_runs if e["pytest"].get("passed")) / len(pytest_runs)

    xrpl_ok_rate = 0.0
    if xrpl_runs:
        xrpl_ok_rate = sum(1 for e in xrpl_runs if e["xrpl"].get("ok")) / len(xrpl_runs)

    durations = [e["pytest"]["duration_ms"] for e in pytest_runs if e.get("pytest", {}).get("duration_ms")]
    avg_pytest_ms = round(sum(durations) / len(durations), 1) if durations else 0.0

    proposal_history = load_proposal_history(limit=20)
    title_counts: Counter = Counter()
    for batch in proposal_history:
        for p in batch.get("proposals", []):
            title_counts[p.get("title", "")] += 1
    stale_proposals = [t for t, c in title_counts.items() if c >= 3 and t]
    factory_state = FactoryState()
    implemented = sorted(set(BUILTIN_IMPLEMENTED) | set(factory_state.get_implemented_proposals()))
    stale_proposals = filter_stale_proposals(stale_proposals, factory_state=factory_state)

    return {
        "tool_cycles_logged": len(tool_entries),
        "pytest_pass_rate": round(pytest_pass_rate, 3),
        "xrpl_ok_rate": round(xrpl_ok_rate, 3),
        "avg_pytest_duration_ms": avg_pytest_ms,
        "proposal_batches": len(proposal_history),
        "implemented_proposals": implemented,
        "stale_proposals": stale_proposals[:5],
        "gate_trends": analyze_gate_trends(),
        "ledger_trends": analyze_ledger_trends(),
    }


def compute_cycle_focus(
    cycle_id: int,
    analysis: Dict[str, Any],
    meta: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Forced rotation every 3rd cycle; otherwise capped score-based weighting.
    Prevents revenue_gap from permanently starving tools/RSI work.
    """
    meta = meta or analyze_improvement_history()
    rotation_slot = FOCUS_ROTATION[(cycle_id - 1) % len(FOCUS_ROTATION)]
    if cycle_id % 3 == 0:
        return rotation_slot

    ledger_trends = meta.get("ledger_trends", {})
    revenue_gap = ledger_trends.get("revenue_gap_usd", REVENUE_TARGET_USD)
    stale = meta.get("stale_proposals", [])

    scores = {"revenue": 0.0, "tools": 0.0, "rsi": 0.0}
    scores[rotation_slot] += 3.0

    if revenue_gap > 0:
        scores["revenue"] += min(1.5, revenue_gap * 0.15)
    if analysis.get("cycle_revenue_usd", 0) <= 0:
        scores["revenue"] += 0.5

    if meta.get("pytest_pass_rate", 1.0) < 1.0:
        scores["tools"] += 3.0
    if meta.get("xrpl_ok_rate", 1.0) < 0.95:
        scores["tools"] += 3.0
    if "gates_failed" in analysis.get("bottlenecks", []):
        scores["tools"] += 2.0

    if stale:
        scores["rsi"] += 2.0 + min(len(stale), 3) * 0.5

    return max(scores, key=scores.get)


def run_self_improvement_meta(
    cycle_id: int,
    analysis: Dict[str, Any],
    gate_result: Dict[str, Any],
) -> Dict[str, Any]:
    """Phase 3b — RSI meta-analysis logged to rsi_improvements.jsonl."""
    meta = analyze_improvement_history()
    focus = compute_cycle_focus(cycle_id, analysis, meta)

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "cycle_id": cycle_id,
        "focus": focus,
        "gates_passed": gate_result.get("all_passed", False),
        "analysis_summary": {
            "cycle_revenue_usd": analysis.get("cycle_revenue_usd"),
            "bottlenecks": analysis.get("bottlenecks"),
            "recommendations": analysis.get("recommendations", [])[:5],
        },
        **meta,
    }
    _append_rsi_log(entry)

    ledger.log_event(
        event_type="milestone",
        source="self_improver",
        amount_usd_est=0.0,
        cycle_id=cycle_id,
        metadata={"phase": "rsi_meta", "focus": focus, **meta},
        anchor_to_xrpl=False,
    )

    return {"focus": focus, **meta}


def self_improvement_proposals(
    meta: Dict[str, Any],
    analysis: Dict[str, Any],
    cycle_id: int,
) -> List[Dict[str, Any]]:
    """Proposals with source=self_improvement driven by meta-analysis."""
    proposals: List[Dict[str, Any]] = []
    focus = meta.get("focus", "revenue")
    stale = meta.get("stale_proposals", [])
    ledger_trends = meta.get("ledger_trends", {})
    gate_trends = meta.get("gate_trends", {})

    if stale:
        stale_target = stale[0]
        if stale_target.lower().startswith("diversify beyond stale proposal:"):
            stale_target = stale_target.split(":", 1)[1].strip()
        proposals.append({
            "title": f"Diversify beyond stale proposal: {stale_target[:60]}",
            "impact": "Break RSI stagnation — implement or retire repeated proposals",
            "verification": "Next cycle proposals differ; gate pass rate stable",
            "source": "self_improvement",
            "focus": focus,
        })

    if ledger_trends.get("revenue_gap_usd", 0) > 0:
        proposals.append({
            "title": "Accelerate treasury-visible payment surfaces",
            "impact": f"Close ${ledger_trends['revenue_gap_usd']:.2f} gap to ${REVENUE_TARGET_USD} target",
            "verification": "verified_revenue_events increases; XRPL tx on testnet explorer",
            "source": "self_improvement",
            "focus": "revenue",
        })

    if gate_trends.get("pass_rate", 1.0) < 0.9 and gate_trends.get("top_failures"):
        top_gate, count = gate_trends["top_failures"][0]
        proposals.append({
            "title": f"Fix recurring gate failure: {top_gate}",
            "impact": f"Gate failed {count} times in recent cycles",
            "verification": f"gate {top_gate} passes 3 consecutive cycles",
            "source": "self_improvement",
            "focus": "tools",
        })

    if meta.get("avg_pytest_duration_ms", 0) > 5000:
        proposals.append({
            "title": "Optimize pytest suite duration",
            "impact": f"Avg pytest {meta['avg_pytest_duration_ms']}ms — reduce cycle latency",
            "verification": "avg_pytest_duration_ms trends down over 5 cycles",
            "source": "self_improvement",
            "focus": "tools",
        })

    if not proposals:
        proposals.append({
            "title": "RSI balance check — maintain revenue/tools/rsi rotation",
            "impact": "Sustain positive evolution velocity without proposal duplication",
            "verification": "rsi_improvements.jsonl grows; focus rotates across domains",
            "source": "self_improvement",
            "focus": focus,
        })

    return proposals


def evolve_self(
    cycle_id: int,
    proposals: List[Dict[str, Any]],
    gate_result: Dict[str, Any],
    meta: Dict[str, Any],
) -> Dict[str, Any]:
    """Record RSI evolution intent when gates pass."""
    if not gate_result.get("all_passed"):
        return {"rsi_evolved": False, "reason": "gates_failed", "focus": meta.get("focus")}

    rsi_proposals = [p for p in proposals if p.get("source") == "self_improvement"]
    _append_rsi_log({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "cycle_id": cycle_id,
        "phase": "evolve_self",
        "focus": meta.get("focus"),
        "proposals_applied": len(rsi_proposals),
        "proposals": rsi_proposals,
    })
    return {
        "rsi_evolved": True,
        "focus": meta.get("focus"),
        "rsi_proposals": rsi_proposals,
        "stale_proposals_detected": meta.get("stale_proposals", []),
        "note": "RSI meta logged; surgical changes via agent/grok review.",
    }