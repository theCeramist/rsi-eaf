#!/usr/bin/env python3
"""
Launch factory_ops_keeper detached from Grok CLI / Job Objects.

  python -u scripts/launch_ops_keeper_detached.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
STATE = RUNTIME / "factory_ops_keeper_launch.json"


def main() -> int:
    os.chdir(ROOT)
    # Load .env lightly
    env_path = ROOT / ".env"
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

    os.environ.update(
        {
            "PYTHONUNBUFFERED": "1",
            "PYTHONPATH": str(ROOT),
            "SUPERVISOR_KEEPER": "false",
            "OPS_KEEPER_INTERVAL_SEC": os.getenv("OPS_KEEPER_INTERVAL_SEC", "90"),
            "OPS_KEEPER_COOLDOWN_SEC": os.getenv("OPS_KEEPER_COOLDOWN_SEC", "120"),
            "FACTORY_MAX_RUNTIME_SEC": "0",
        }
    )

    RUNTIME.mkdir(parents=True, exist_ok=True)
    log = RUNTIME / "factory_ops_keeper_tee.log"

    # Avoid multiple keepers
    try:
        r = subprocess.run(
            [
                "wmic",
                "process",
                "where",
                "name='python.exe'",
                "get",
                "ProcessId,CommandLine",
                "/FORMAT:CSV",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        for line in (r.stdout or "").splitlines():
            if "factory_ops_keeper.py" in line and "launch_ops_keeper" not in line:
                print("ops_keeper already running — not double-launching")
                print(line[:200])
                return 0
    except Exception:
        pass

    # Prefer proven flags: NEW_GROUP|NO_WINDOW. Avoid BREAKAWAY (Access Denied).
    # DETACHED optional — can help outlive console; try with then without.
    CREATE_NEW_PROCESS_GROUP = 0x00000200
    DETACHED_PROCESS = 0x00000008
    CREATE_NO_WINDOW = 0x08000000
    flag_try = [
        CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW,
        CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW | DETACHED_PROCESS,
        CREATE_NEW_PROCESS_GROUP,
        0,
    ]
    # Reuse cache from ops keeper if present
    cache = RUNTIME / "ops_spawn_flags.json"
    if cache.is_file():
        try:
            cached = int(json.loads(cache.read_text(encoding="utf-8")).get("flags"))
            flag_try = [cached] + [f for f in flag_try if f != cached]
        except Exception:
            pass

    p = None
    last_err: Exception | None = None
    for flags in flag_try:
        try:
            with log.open("a", encoding="utf-8") as fh:
                fh.write(
                    f"\n--- launch ops keeper {datetime.now(timezone.utc).isoformat()} "
                    f"flags=0x{flags:x} ---\n"
                )
                fh.flush()
                p = subprocess.Popen(
                    [
                        sys.executable,
                        "-u",
                        str(ROOT / "scripts" / "factory_ops_keeper.py"),
                        "--interval",
                        os.getenv("OPS_KEEPER_INTERVAL_SEC", "90"),
                        "--cooldown",
                        os.getenv("OPS_KEEPER_COOLDOWN_SEC", "120"),
                    ],
                    cwd=str(ROOT),
                    env=os.environ.copy(),
                    stdout=fh,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    creationflags=flags if sys.platform == "win32" else 0,
                    close_fds=True,
                    start_new_session=(sys.platform != "win32"),
                )
            break
        except OSError as exc:
            last_err = exc
            # Access Denied — try next flag set
            continue
    if p is None:
        raise SystemExit(f"failed to launch ops_keeper: {last_err}")

    meta = {
        "schema": "rsi_eaf_ops_keeper_launch_v1",
        "launched_at": datetime.now(timezone.utc).isoformat(),
        "keeper_pid": p.pid,
        "interval_sec": os.getenv("OPS_KEEPER_INTERVAL_SEC", "90"),
        "cooldown_sec": os.getenv("OPS_KEEPER_COOLDOWN_SEC", "120"),
        "log": str(log),
        "state": str(RUNTIME / "factory_ops_keeper_state.json"),
    }
    STATE.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"ops_keeper launched pid={p.pid}")
    print(f"state: {STATE}")
    print(f"log: {log}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
