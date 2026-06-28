"""
Economic circuit breakers, adaptive intervals, and success stop conditions.
"""

import os
from typing import Any, Dict, Optional, Tuple

REVENUE_TARGET_USD = float(os.getenv("REVENUE_TARGET_USD", "10.0"))
DEFAULT_MAX_CUMULATIVE_NET_LOSS_USD = 60.0


def max_cumulative_net_loss_usd() -> float:
    return float(os.getenv("MAX_CUMULATIVE_NET_LOSS_USD", str(DEFAULT_MAX_CUMULATIVE_NET_LOSS_USD)))


def loss_ceiling_raised() -> bool:
    return max_cumulative_net_loss_usd() > DEFAULT_MAX_CUMULATIVE_NET_LOSS_USD


def requires_revenue_action(net: Dict[str, Any]) -> bool:
    """Raised ceiling only valid when paired with active revenue/distribution work."""
    if not loss_ceiling_raised():
        return False
    return float(net.get("net_usd_est", 0)) <= -DEFAULT_MAX_CUMULATIVE_NET_LOSS_USD
MIN_REVENUE_COST_RATIO = float(os.getenv("MIN_REVENUE_COST_RATIO", "0.1"))
ZERO_REVENUE_CYCLE_LIMIT = int(os.getenv("ZERO_REVENUE_CYCLE_LIMIT", "5"))
SUCCESS_POSITIVE_CYCLES = int(os.getenv("SUCCESS_POSITIVE_CYCLES", "3"))
BASE_INTERVAL_MINUTES = float(os.getenv("CYCLE_INTERVAL_MINUTES", "5"))
ADAPTIVE_INTERVAL_MINUTES = float(os.getenv("ADAPTIVE_INTERVAL_MINUTES", "30"))
ADAPTIVE_INTERVAL_MAX_MINUTES = float(os.getenv("ADAPTIVE_INTERVAL_MAX_MINUTES", "60"))


def revenue_cost_ratio(net: Dict[str, Any]) -> float:
    cost = max(float(net.get("total_cost_usd_est", 0)), 0.01)
    return float(net.get("total_revenue_usd_est", 0)) / cost


def continuous_run_enabled() -> bool:
    """External caps may govern spend — skip cumulative-net stop when enabled."""
    return os.getenv("FACTORY_RUN_CONTINUOUS", "false").lower() in {"1", "true", "yes"}


def evaluate_circuit_breakers(
    net: Dict[str, Any],
    consecutive_zero_revenue: int,
    mode: str = "hybrid",
) -> Tuple[Optional[str], Optional[str]]:
    """
    Returns (stop_reason, throttle_mode).
    throttle_mode switches autonomous runner to tool_improvement when economics fail.
    """
    cumulative_net = float(net.get("net_usd_est", 0))
    ratio = revenue_cost_ratio(net)

    ceiling = max_cumulative_net_loss_usd()
    if not continuous_run_enabled() and cumulative_net <= -ceiling:
        return (
            f"cumulative net ${cumulative_net:.2f} below -${ceiling:.2f} ceiling",
            "tool_improvement",
        )

    if (
        not continuous_run_enabled()
        and float(net.get("total_revenue_usd_est", 0)) > 0
        and ratio < MIN_REVENUE_COST_RATIO
        and consecutive_zero_revenue >= ZERO_REVENUE_CYCLE_LIMIT
    ):
        return (
            f"revenue/cost ratio {ratio:.3f} < {MIN_REVENUE_COST_RATIO} "
            f"after {consecutive_zero_revenue} zero-revenue cycles",
            "tool_improvement",
        )

    if (
        consecutive_zero_revenue >= ZERO_REVENUE_CYCLE_LIMIT
        and mode == "hybrid"
        and not continuous_run_enabled()
    ):
        return (
            None,
            "tool_improvement",
        )

    return None, None


def evaluate_success_stop(
    net: Dict[str, Any],
    consecutive_positive_net: int,
) -> Optional[str]:
    revenue = float(net.get("total_revenue_usd_est", 0))
    if revenue >= REVENUE_TARGET_USD and consecutive_positive_net >= SUCCESS_POSITIVE_CYCLES:
        return (
            f"revenue ${revenue:.2f} >= ${REVENUE_TARGET_USD:.2f} "
            f"and {consecutive_positive_net} consecutive positive-net cycles"
        )
    return None


def compute_sleep_minutes(
    base_interval: float,
    cycle_revenue_usd: float,
    consecutive_zero_revenue: int,
) -> float:
    """Slow down when cycles produce no verified revenue."""
    if cycle_revenue_usd > 0:
        return base_interval
    if consecutive_zero_revenue <= 1:
        return base_interval
    max_interval = ADAPTIVE_INTERVAL_MAX_MINUTES
    if continuous_run_enabled():
        max_interval = float(
            os.getenv("CONTINUOUS_ADAPTIVE_MAX_MINUTES", str(min(ADAPTIVE_INTERVAL_MAX_MINUTES, 20)))
        )
    scaled = ADAPTIVE_INTERVAL_MINUTES * min(consecutive_zero_revenue, 4)
    return min(max(base_interval, scaled), max_interval)


def evaluate_raised_ceiling_revenue_action(
    net: Dict[str, Any],
    distribution_result: Optional[Dict[str, Any]],
) -> Optional[str]:
    """Stop if user raised loss ceiling but cycle did not execute a revenue action."""
    if not requires_revenue_action(net):
        return None
    dist = distribution_result or {}
    if dist.get("pushed") or dist.get("issue_updated"):
        return None
    return (
        f"loss ceiling raised to ${max_cumulative_net_loss_usd():.0f} past "
        f"-${DEFAULT_MAX_CUMULATIVE_NET_LOSS_USD:.0f} — requires GitHub distribution "
        "or issue refresh each cycle"
    )