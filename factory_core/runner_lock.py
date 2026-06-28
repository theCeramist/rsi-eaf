"""
Single-instance lock for autonomous factory runner processes.
Supports lane-specific locks: hybrid | revenue | tools.
"""

import atexit
import os
import sys
from pathlib import Path
from typing import Optional

_LANE = os.getenv("FACTORY_RUNNER_LANE", "hybrid").strip().lower()
_LOCK_PATH = os.getenv(
    "FACTORY_RUNNER_LOCK",
    f"factory_core/.runner.{_LANE}.lock" if _LANE != "hybrid" else "factory_core/.runner.lock",
)
LOCK_FILE = Path(_LOCK_PATH)


def runner_lane() -> str:
    return _LANE


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import subprocess

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


def _read_lock_pid() -> Optional[int]:
    if not LOCK_FILE.exists():
        return None
    try:
        raw = LOCK_FILE.read_text(encoding="utf-8").strip()
        return int(raw.splitlines()[0])
    except (OSError, ValueError):
        return None


def _release_lock() -> None:
    try:
        if LOCK_FILE.exists() and _read_lock_pid() == os.getpid():
            LOCK_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def acquire_runner_lock(lane: Optional[str] = None) -> bool:
    """
    Claim the runner lock for this process (lane-specific file).
    Returns False if another live runner holds the lock.
    """
    global LOCK_FILE
    if lane:
        LOCK_FILE = Path(
            os.getenv(
                "FACTORY_RUNNER_LOCK",
                f"factory_core/.runner.{lane}.lock" if lane != "hybrid" else "factory_core/.runner.lock",
            )
        )
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    existing = _read_lock_pid()
    if existing and existing != os.getpid() and _pid_alive(existing):
        return False
    LOCK_FILE.write_text(f"{os.getpid()}\n", encoding="utf-8")
    atexit.register(_release_lock)
    return True


def require_runner_lock(lane: Optional[str] = None) -> None:
    if acquire_runner_lock(lane):
        return
    holder = _read_lock_pid()
    active_lane = lane or _LANE
    print(
        f"[AutonomousRunner] Another {active_lane} runner is active (pid={holder}). "
        "Exiting to avoid duplicate cycles."
    )
    sys.exit(0)