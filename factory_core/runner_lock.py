"""
Single-instance lock for autonomous factory runner processes.
"""

import atexit
import os
import sys
from pathlib import Path
from typing import Optional

LOCK_FILE = Path(os.getenv("FACTORY_RUNNER_LOCK", "factory_core/.runner.lock"))


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


def acquire_runner_lock() -> bool:
    """
    Claim the runner lock for this process.
    Returns False if another live runner holds the lock.
    """
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    existing = _read_lock_pid()
    if existing and existing != os.getpid() and _pid_alive(existing):
        return False
    LOCK_FILE.write_text(f"{os.getpid()}\n", encoding="utf-8")
    atexit.register(_release_lock)
    return True


def require_runner_lock() -> None:
    if acquire_runner_lock():
        return
    holder = _read_lock_pid()
    print(
        f"[AutonomousRunner] Another runner is active (pid={holder}). "
        "Exiting to avoid duplicate cycles."
    )
    sys.exit(0)