"""
Session cost tracking for RSI-EAF.

Logs verifiable operational costs (LLM tokens, API usage, etc.) to the economic ledger.
Auto-ingests Grok Build per-turn token usage from ~/.grok/sessions when available.
"""

import os
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from observability.economic_ledger import ledger
from observability.grok_usage import (
    GrokUsageSnapshot,
    build_watermark_after_ingest,
    collect_new_usage,
)

if TYPE_CHECKING:
    from factory_core.state import FactoryState

GROK_COST_PER_1K_TOKENS = float(os.getenv("GROK_BUILD_COST_PER_1K_TOKENS", "0.10"))
DEFAULT_SESSION_COST_USD = os.getenv("CYCLE_SESSION_COST_USD")
AUTO_GROK_USAGE = os.getenv("AUTO_GROK_USAGE", "true").lower() in {"1", "true", "yes"}
GROK_MAX_TOKENS_PER_CYCLE = int(os.getenv("GROK_MAX_TOKENS_PER_CYCLE", "8000"))


def estimate_grok_cost_usd(tokens_used: int) -> float:
    return round((tokens_used / 1000.0) * GROK_COST_PER_1K_TOKENS, 4)


def log_cycle_costs(
    cycle_id: int,
    session_cost_usd: Optional[float] = None,
    grok_tokens_used: Optional[int] = None,
    source: str = "grok_build",
    metadata: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    Log cycle costs to the economic ledger.

    Priority: explicit session_cost_usd > token-based estimate > CYCLE_SESSION_COST_USD env.
    """
    costs: List[Dict[str, Any]] = []
    extra = metadata or {}

    if session_cost_usd is not None and (session_cost_usd > 0 or extra.get("tool_maintenance")):
        amount = session_cost_usd if session_cost_usd is not None else 0.0
        basis = extra.get("basis") or "explicit_session_cost"
    elif grok_tokens_used is not None and grok_tokens_used > 0:
        amount = estimate_grok_cost_usd(grok_tokens_used)
        basis = "grok_token_estimate"
        extra = {
            **extra,
            "grok_tokens_used": grok_tokens_used,
            "cost_per_1k_tokens": GROK_COST_PER_1K_TOKENS,
        }
    elif DEFAULT_SESSION_COST_USD:
        amount = float(DEFAULT_SESSION_COST_USD)
        basis = "env_cycle_session_cost_usd"
    else:
        return costs

    event = ledger.log_event(
        event_type="cost",
        source=source,
        amount_usd_est=amount,
        cycle_id=cycle_id,
        metadata={
            "basis": basis,
            "notes": "Operational cost for factory cycle (LLM/API/compute)",
            **extra,
        },
        anchor_to_xrpl=False,
    )
    costs.append(event)
    print(f"[CostTracker] Logged ${amount:.4f} cost for cycle {cycle_id} ({basis})")
    return costs


def auto_log_grok_session_costs(
    cycle_id: int,
    factory_state: Optional["FactoryState"] = None,
    cwd: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Pull per-message Grok token usage from session logs and log unbilled deltas.
    Updates factory_state grok_usage_watermark when provided.
    """
    if not AUTO_GROK_USAGE:
        return []
    if os.getenv("FACTORY_RUNNER_ACTIVE", "").lower() not in {"1", "true", "yes"}:
        return []

    watermark = factory_state.get_grok_usage_watermark() if factory_state else {}
    snapshot = collect_new_usage(watermark=watermark, cwd=cwd)
    if not snapshot:
        return []

    if snapshot.bootstrapped:
        new_watermark = build_watermark_after_ingest(snapshot)
        if factory_state:
            factory_state.set_grok_usage_watermark(new_watermark)
        print(
            "[GrokUsage] Bootstrapped watermark for session "
            f"{snapshot.session_id} (no retroactive charge)."
        )
        return []

    if snapshot.tokens_new <= 0:
        print("[GrokUsage] No new Grok token usage since last cycle.")
        if factory_state:
            factory_state.set_grok_usage_watermark(build_watermark_after_ingest(snapshot))
        return []

    tokens_to_bill = snapshot.tokens_new
    if tokens_to_bill > GROK_MAX_TOKENS_PER_CYCLE:
        print(
            f"[GrokUsage] Capping cycle bill {tokens_to_bill} → "
            f"{GROK_MAX_TOKENS_PER_CYCLE} tokens (GROK_MAX_TOKENS_PER_CYCLE)."
        )
        tokens_to_bill = GROK_MAX_TOKENS_PER_CYCLE

    turn_breakdown = [
        {
            "prompt_id": t.prompt_id,
            "tokens_delta": t.tokens_delta,
            "completed": t.completed,
            "user_preview": t.user_preview,
        }
        for t in snapshot.turns_new
    ]

    costs = log_cycle_costs(
        cycle_id=cycle_id,
        grok_tokens_used=tokens_to_bill,
        metadata={
            "basis": "grok_session_auto",
            "source_artifact": snapshot.session_dir,
            "session_id": snapshot.session_id,
            "context_tokens_used": snapshot.context_tokens_used,
            "context_window_tokens": snapshot.context_window_tokens,
            "turn_breakdown": turn_breakdown,
            "verification_method": "grok_updates_jsonl_totalTokens_delta",
        },
    )

    if factory_state:
        factory_state.set_grok_usage_watermark(build_watermark_after_ingest(snapshot))

    print(
        f"[GrokUsage] Auto-ingested {snapshot.tokens_new} tokens "
        f"from {len(snapshot.turns_new)} turn(s)."
    )
    return costs


def grok_spend_usd_recent(limit_events: int = 500) -> float:
    """Sum logged Grok-related costs from the economic ledger."""
    total = 0.0
    for event in ledger.get_recent_events(limit=limit_events):
        if event.get("event_type") != "cost":
            continue
        meta = event.get("metadata") or {}
        basis = str(meta.get("basis", ""))
        source = str(event.get("source", ""))
        if "grok" in basis.lower() or "grok" in source.lower():
            total += float(event.get("amount_usd_est", 0))
    return round(total, 4)


def grok_budget_ok(budget_usd: float, window_events: int = 500) -> bool:
    """True when cumulative Grok spend is below the configured evolution budget."""
    if budget_usd <= 0:
        return False
    return grok_spend_usd_recent(window_events) < budget_usd