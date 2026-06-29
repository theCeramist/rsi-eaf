"""
Graceful factory shutdown — stop runner, daemons, persist closure state.

Usage:
  python scripts/shutdown_factory.py --reason "awaiting additional funds"
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv

load_dotenv()

CLOSURE_FILE = Path(os.getenv("FACTORY_CLOSURE_FILE", "observability/factory_closure.json"))
LOCK_GLOB = "factory_core/.runner*.lock"


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True,
            text=True,
            check=False,
        )
        return str(pid) in (result.stdout or "")
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _stop_runner_processes() -> list[dict]:
    stopped: list[dict] = []
    root = Path(__file__).resolve().parent.parent
    for lock_path in root.glob(LOCK_GLOB):
        try:
            pid = int(lock_path.read_text(encoding="utf-8").strip().splitlines()[0])
        except (OSError, ValueError):
            pid = 0
        if pid and _pid_alive(pid):
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(pid), "/F"], check=False)
            else:
                import signal

                os.kill(pid, signal.SIGTERM)
            stopped.append({"pid": pid, "lock": str(lock_path), "action": "terminated"})
        try:
            lock_path.unlink(missing_ok=True)
        except OSError:
            pass
    return stopped


def shutdown_factory(*, reason: str) -> dict:
    from factory_core.state import FactoryState
    from observability.economic_ledger import ledger
    from observability.factory_health import persist_factory_health

    print("[Shutdown] Stopping runner processes...")
    runner_stops = _stop_runner_processes()

    print("[Shutdown] Stopping background daemons...")
    try:
        from observability.daemon_supervisor import stop_all_factory_daemons

        stop_all_factory_daemons()
        daemons_stopped = True
    except Exception as exc:
        daemons_stopped = False
        daemon_error = str(exc)
    else:
        daemon_error = None

    net = ledger.calculate_net()
    now = datetime.now(timezone.utc).isoformat()
    resume_cmd = "python scripts/run_continuous_hybrid.py"

    closure = {
        "schema": "rsi_eaf_factory_closure_v1",
        "state": "closed_indefinitely",
        "closed_at": now,
        "reason": reason,
        "cycles_completed": FactoryState().snapshot().get("cycles_completed"),
        "current_cycle": FactoryState().snapshot().get("current_cycle"),
        "ledger_net": net,
        "runner_stops": runner_stops,
        "daemons_stopped": daemons_stopped,
        "resume": {
            "command": resume_cmd,
            "note": "Factory resumes toward positive net economic activity when restarted.",
            "prerequisites": [
                "Additional operating funds available (Grok + infra buffer)",
                "FACTORY_XRPL_SEED and treasury configured in .env",
                "Optional: external payers via agent-pay.json for organic revenue",
            ],
        },
    }

    CLOSURE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CLOSURE_FILE.write_text(json.dumps(closure, indent=2), encoding="utf-8")

    state = FactoryState()
    state.set_operational_status(
        {
            "state": "closed_indefinitely",
            "closed_at": now,
            "reason": reason,
            "resume_command": resume_cmd,
        }
    )

    os.environ.pop("FACTORY_RUNNER_ACTIVE", None)
    health_path = persist_factory_health(
        cycle_id=int(state.current_cycle),
        factory_state=state.snapshot(),
    )
    closure["factory_health"] = str(health_path)

    print(f"[Shutdown] Closure recorded: {CLOSURE_FILE}")
    print(f"[Shutdown] Resume with: {resume_cmd}")
    print(f"[Shutdown] Final net: ${net.get('net_usd_est', 0):.2f} | organic=${net.get('organic_revenue_usd_est', 0):.2f}")
    if daemon_error:
        closure["daemon_error"] = daemon_error
    return closure


def main() -> None:
    parser = argparse.ArgumentParser(description="Gracefully shut down RSI-EAF factory")
    parser.add_argument(
        "--reason",
        default="indefinite closure — awaiting additional funds",
        help="Recorded reason for shutdown",
    )
    args = parser.parse_args()
    shutdown_factory(reason=args.reason)


if __name__ == "__main__":
    main()