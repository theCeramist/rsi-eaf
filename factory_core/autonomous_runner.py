"""
Autonomous factory runner — scheduled cycles with stop conditions.
"""

import argparse
import os
import sys
import time
from typing import Optional

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from factory_core.cycle_runner import CycleRunner
from observability.economic_ledger import ledger

CYCLE_INTERVAL_MINUTES = float(os.getenv("CYCLE_INTERVAL_MINUTES", "60"))
MAX_CONSECUTIVE_NEGATIVE = int(os.getenv("MAX_CONSECUTIVE_NEGATIVE_CYCLES", "5"))
MIN_XRP_RESERVE = float(os.getenv("MIN_XRP_RESERVE", "10.0"))


def should_stop(consecutive_negative: int, xrpl_balance: float) -> Optional[str]:
    if consecutive_negative >= MAX_CONSECUTIVE_NEGATIVE:
        return f"{MAX_CONSECUTIVE_NEGATIVE} consecutive negative-net cycles"
    if xrpl_balance < MIN_XRP_RESERVE:
        return f"XRPL balance {xrpl_balance} below reserve {MIN_XRP_RESERVE}"
    return None


def run_autonomous(max_cycles: Optional[int] = None, interval_minutes: float = CYCLE_INTERVAL_MINUTES) -> None:
    runner = CycleRunner()
    consecutive_negative = 0
    cycles_run = 0

    print(f"[AutonomousRunner] Starting (interval={interval_minutes}m, max_cycles={max_cycles or 'unlimited'})")

    while True:
        if max_cycles is not None and cycles_run >= max_cycles:
            print("[AutonomousRunner] Reached max_cycles limit.")
            break

        result = runner.run_cycle(manual=False)
        cycles_run += 1

        net_cycle = result.get("analysis", {}).get("net_this_cycle", {})
        if net_cycle.get("net_usd_est", 0) < 0:
            consecutive_negative += 1
        else:
            consecutive_negative = 0

        stop_reason = should_stop(consecutive_negative, result.get("current_xrp_balance", 0))
        if stop_reason:
            print(f"[AutonomousRunner] Stopping: {stop_reason}")
            break

        if max_cycles is None or cycles_run < max_cycles:
            sleep_sec = int(interval_minutes * 60)
            print(f"[AutonomousRunner] Sleeping {sleep_sec}s until next cycle...")
            time.sleep(sleep_sec)

    print("[AutonomousRunner] Final net:", ledger.calculate_net())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run RSI-EAF autonomously on a schedule")
    parser.add_argument("--max-cycles", type=int, default=None)
    parser.add_argument("--interval-minutes", type=float, default=CYCLE_INTERVAL_MINUTES)
    args = parser.parse_args()
    run_autonomous(max_cycles=args.max_cycles, interval_minutes=args.interval_minutes)