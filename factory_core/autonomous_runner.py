"""
Autonomous factory runner — scheduled cycles with economic guards and adaptive pacing.

Cycling decisions (mode, sleep, stop, evolution priority) are owned by FactoryDirector.
"""

import argparse
import os
import sys
import time
from typing import Optional

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv

load_dotenv()

from factory_core.cycle_runner import CycleRunner
from factory_core.director import CyclePlan, director

from factory_core.runner_lock import require_runner_lock
from factory_core.economic_guards import (
    BASE_INTERVAL_MINUTES,
    DEFAULT_MAX_CUMULATIVE_NET_LOSS_USD,
    REVENUE_TARGET_USD,
    continuous_run_enabled,
    loss_ceiling_raised,
    max_cumulative_net_loss_usd,
)
from factory_core.self_improver import analyze_improvement_history
from observability.economic_ledger import ledger

CYCLE_INTERVAL_MINUTES = float(os.getenv("CYCLE_INTERVAL_MINUTES", str(BASE_INTERVAL_MINUTES)))
REVENUE_PURSUIT = os.getenv("REVENUE_PURSUIT", "true").lower() in {"1", "true", "yes"}


def run_autonomous(
    max_cycles: Optional[int] = None,
    interval_minutes: float = CYCLE_INTERVAL_MINUTES,
    mode: str = "hybrid",
) -> None:
    require_runner_lock()
    os.environ["FACTORY_RUNNER_ACTIVE"] = "true"

    from factory_core.runner_preflight import run_preflight

    preflight = run_preflight()
    print(f"[AutonomousRunner] Preflight ok={preflight['ok']} top3={preflight.get('top3_revenue')}")
    for w in preflight.get("warnings", [])[:4]:
        print(f"[AutonomousRunner] Preflight warning: {w}")
    if not preflight.get("ok") and os.getenv("FACTORY_PREFLIGHT_BLOCK", "true").lower() in {"1", "true", "yes"}:
        for b in preflight.get("blockers", []):
            print(f"[AutonomousRunner] Preflight blocker: {b}")
        raise RuntimeError("Runner preflight failed — fix blockers before restart")

    from factory_core.parallel_lanes import start_all_parallel_infrastructure
    from factory_core.runner_lock import runner_lane

    daemon_results = start_all_parallel_infrastructure()
    lane = runner_lane()
    for daemon in daemon_results:
        if daemon.get("started"):
            meta = daemon.get("meta", {})
            name = daemon.get("name", "unknown")
            detail = meta.get("treasury_address") or meta.get("interval_sec") or meta
            print(f"[AutonomousRunner] Daemon {name} started: {detail}")
    print(f"[AutonomousRunner] Runner lane={lane} parallel_daemons={len(daemon_results)}")

    runner = CycleRunner()
    acp_boot: dict = {"started": False}
    if os.getenv("GROK_ORCHESTRATION", "subprocess").lower() == "acp":
        from factory_core.grok_acp import init_runner_acp

        acp_boot = init_runner_acp(runner.state)
        if acp_boot.get("started"):
            print(
                f"[AutonomousRunner] ACP orchestration active "
                f"session={acp_boot.get('session_id')} reused={acp_boot.get('reused')}"
            )
        else:
            print(f"[AutonomousRunner] ACP start skipped: {acp_boot.get('reason') or acp_boot.get('error')}")

    consecutive_negative = 0
    consecutive_zero_revenue = 0
    consecutive_positive_net = 0
    cycles_run = 0
    active_mode = mode

    # Initial plan from director defaults
    next_plan = CyclePlan(
        cycle_id_next=runner.state.current_cycle + 1,
        mode=active_mode,
        focus="revenue",
        sleep_minutes=interval_minutes,
        reasoning={"bootstrap": True},
    )
    director.configure_autonomous_env(next_plan)

    meta = analyze_improvement_history()
    net = ledger.calculate_net()
    ceiling = max_cumulative_net_loss_usd()
    if continuous_run_enabled():
        print(
            "[AutonomousRunner] FACTORY_RUN_CONTINUOUS=true — "
            "cumulative net stop disabled (external caps apply)"
        )
    if loss_ceiling_raised() and not continuous_run_enabled():
        print(
            f"[AutonomousRunner] WARNING: loss ceiling raised to ${ceiling:.0f} "
            f"(default ${DEFAULT_MAX_CUMULATIVE_NET_LOSS_USD:.0f}) — "
            "requires GitHub distribution each cycle past -$60"
        )
    print(
        f"[AutonomousRunner] mode={active_mode} interval={interval_minutes}m "
        f"max_cycles={max_cycles or 'unlimited'} "
        f"VERCEL_DEPLOY={os.getenv('VERCEL_DEPLOY')} "
        f"REVENUE_PURSUIT={REVENUE_PURSUIT} target=${REVENUE_TARGET_USD} "
        f"loss_ceiling=-${ceiling:.0f} "
        f"revenue_gap=${meta.get('ledger_trends', {}).get('revenue_gap_usd', 0):.2f} "
        f"organic=${net.get('organic_revenue_usd_est', 0):.2f} "
        f"director=FactoryDirector"
    )

    try:
        while True:
            if max_cycles is not None and cycles_run >= max_cycles:
                print("[AutonomousRunner] Reached max_cycles limit.")
                break

            director.configure_autonomous_env(next_plan)
            os.environ["FACTORY_CONSECUTIVE_ZERO_REVENUE"] = str(consecutive_zero_revenue)
            print(
                f"[Director] Cycle {next_plan.cycle_id_next} plan: "
                f"mode={next_plan.mode} focus={next_plan.focus} "
                f"evolution={next_plan.evolution_priorities[:2] or 'none'} "
                f"grok={next_plan.allow_grok_evolution}"
            )

            try:
                result = runner.run_cycle(manual=False)
            except Exception as exc:
                print(f"[AutonomousRunner] Cycle error (continuing): {exc}")
                cycles_run += 1
                time.sleep(int(interval_minutes * 60))
                continue

            cycles_run += 1
            net = result.get("ledger_net", {})
            analysis = result.get("analysis", {})
            net_cycle = analysis.get("net_this_cycle", {})
            cycle_revenue = float(analysis.get("cycle_revenue_usd", 0) or 0)

            if cycle_revenue <= 0:
                consecutive_zero_revenue += 1
            else:
                consecutive_zero_revenue = 0

            if net_cycle.get("net_usd_est", 0) < 0:
                consecutive_negative += 1
                consecutive_positive_net = 0
            else:
                consecutive_negative = 0
                consecutive_positive_net += 1

            focus = analysis.get("cycle_focus", next_plan.focus)
            print(
                f"[AutonomousRunner] Cycle {result.get('cycle_id')} "
                f"mode={active_mode} focus={focus} "
                f"revenue=${net.get('total_revenue_usd_est', 0):.2f} "
                f"organic=${net.get('organic_revenue_usd_est', 0):.2f} "
                f"net=${net.get('net_usd_est', 0):.2f}"
            )

            if acp_boot.get("started"):
                from factory_core.grok_acp import runner_acp_heartbeat

                hb = runner_acp_heartbeat(
                    int(result.get("cycle_id", 0)),
                    result,
                    factory_state=runner.state,
                )
                if not hb.get("skipped"):
                    print(f"[AutonomousRunner] ACP heartbeat cycle={result.get('cycle_id')}")

            next_plan = director.decide_after_cycle(
                result,
                active_mode=active_mode,
                base_interval_minutes=interval_minutes,
                consecutive_negative=consecutive_negative,
                consecutive_zero_revenue=consecutive_zero_revenue,
                consecutive_positive_net=consecutive_positive_net,
            )
            active_mode = next_plan.mode

            if next_plan.throttle_from:
                print(
                    f"[Director] Throttled {next_plan.throttle_from} → {next_plan.mode}: "
                    f"{next_plan.reasoning.get('throttle', '')}"
                )
            if next_plan.reasoning.get("resume"):
                print(f"[Director] Resuming hybrid: {next_plan.reasoning['resume']}")
            if next_plan.reasoning.get("director_override"):
                print(f"[Director] Override: {next_plan.reasoning['director_override']}")

            if next_plan.stop_reason:
                print(f"[Director] Stopping factory: {next_plan.stop_reason}")
                break

            if max_cycles is None or cycles_run < max_cycles:
                sleep_sec = int(next_plan.sleep_minutes * 60)
                print(f"[Director] Sleeping {sleep_sec}s until cycle {next_plan.cycle_id_next}...")
                time.sleep(sleep_sec)
    finally:
        if acp_boot.get("started"):
            from factory_core.grok_acp import shutdown_runner_acp

            shutdown_runner_acp(acp_boot.get("client"))
            print("[AutonomousRunner] ACP session closed")
        try:
            from observability.treasury_daemon import stop_treasury_daemon

            stop_treasury_daemon()
        except Exception:
            pass

    print("[AutonomousRunner] Final net:", ledger.calculate_net())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run RSI-EAF autonomously on a schedule")
    parser.add_argument("--max-cycles", type=int, default=None)
    parser.add_argument("--interval-minutes", type=float, default=CYCLE_INTERVAL_MINUTES)
    parser.add_argument(
        "--mode",
        choices=["hybrid", "tool_improvement", "revenue"],
        default="hybrid",
        help="hybrid = tools + revenue engines + Vercel (default)",
    )
    args = parser.parse_args()
    run_autonomous(
        max_cycles=args.max_cycles,
        interval_minutes=args.interval_minutes,
        mode=args.mode,
    )