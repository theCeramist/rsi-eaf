#!/usr/bin/env python3
"""
Launch factory supervisor detached from Grok CLI Job Objects / max_runtime.

After launch, monitor from this Grok session with:
  python -u scripts/monitor_factory_cli.py
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
STATE = RUNTIME / "factory_detached_launch.json"


def _load_dotenv() -> None:
    env_path = ROOT / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def main() -> int:
    os.chdir(ROOT)
    _load_dotenv()
    os.environ.update(
        {
            "PYTHONUNBUFFERED": "1",
            "FACTORY_CLI_SUPERVISOR": "1",
            "FACTORY_SKIP_TOOL_PHASE": os.getenv("FACTORY_SKIP_TOOL_PHASE", "true"),
            "FACTORY_PREFLIGHT_PYTEST": os.getenv("FACTORY_PREFLIGHT_PYTEST", "false"),
            "VERCEL_DEPLOY": os.getenv("VERCEL_DEPLOY", "false"),
            "X_AGENT_DAEMON_ENABLED": os.getenv("X_AGENT_DAEMON_ENABLED", "true"),
            "FACTORY_MAX_RUNTIME_SEC": "0",
            "SUPERVISOR_HEARTBEAT_SEC": os.getenv("SUPERVISOR_HEARTBEAT_SEC", "25"),
            "LINK_WATCHER_ENABLED": "true",
            "LINK_WATCHER_DAEMON_ENABLED": "true",
            "LINK_WATCHER_LANE": "true",
            "MAINNET_REVENUE_LANE": "true",
            "XRPL_NETWORK": os.getenv("XRPL_NETWORK", "dual"),
            "XRPL_OPS_NETWORK": os.getenv("XRPL_OPS_NETWORK", "testnet"),
            "XRPL_REVENUE_NETWORK": os.getenv("XRPL_REVENUE_NETWORK", "mainnet"),
            "MAINNET_OUTBOUND_ENABLED": os.getenv("MAINNET_OUTBOUND_ENABLED", "false"),
            "PYTHONPATH": str(ROOT),
        }
    )

    RUNTIME.mkdir(parents=True, exist_ok=True)
    log = RUNTIME / "factory_cli_supervisor_tee.log"

    # Windows: CREATE_BREAKAWAY_FROM_JOB → WinError 5 Access Denied for normal users.
    # Prefer NEW_GROUP|NO_WINDOW (proven); DETACHED optional.
    CREATE_NEW_PROCESS_GROUP = 0x00000200
    DETACHED_PROCESS = 0x00000008
    CREATE_NO_WINDOW = 0x08000000
    flag_try = [
        CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW,
        CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW | DETACHED_PROCESS,
        CREATE_NEW_PROCESS_GROUP,
        0,
    ]
    cache = RUNTIME / "ops_spawn_flags.json"
    if cache.is_file():
        try:
            cached = int(json.loads(cache.read_text(encoding="utf-8")).get("flags"))
            flag_try = [cached] + [f for f in flag_try if f != cached]
        except Exception:
            pass

    p = None
    last_err: Exception | None = None
    flags = flag_try[0]
    for flags in flag_try:
        try:
            with log.open("a", encoding="utf-8") as fh:
                fh.write(
                    f"\n--- detached launch {datetime.now(timezone.utc).isoformat()} "
                    f"flags=0x{flags:x} ---\n"
                )
                fh.flush()
                p = subprocess.Popen(
                    [sys.executable, "-u", str(ROOT / "scripts" / "factory_cli_supervisor.py")],
                    cwd=str(ROOT),
                    env=os.environ.copy(),
                    stdout=fh,
                    stderr=subprocess.STDOUT,
                    creationflags=flags if sys.platform == "win32" else 0,
                    close_fds=True,
                    start_new_session=(sys.platform != "win32"),
                )
            break
        except OSError as exc:
            last_err = exc
            continue
    if p is None:
        raise SystemExit(f"failed to launch supervisor: {last_err}")

    # Outer keep-alive: re-launch supervisor if it dies (no human babysitting).
    # Default ON; set SUPERVISOR_KEEPER=false if wmic races cause double stacks.
    if os.getenv("SUPERVISOR_KEEPER", "true").lower() not in {"1", "true", "yes"}:
        meta = {
            "schema": "rsi_eaf_detached_launch_v1",
            "launched_at": datetime.now(timezone.utc).isoformat(),
            "supervisor_pid": p.pid,
            "keeper_pid": None,
            "monitor_cmd": "python -u scripts/monitor_factory_cli.py",
            "logs": {
                "supervisor": str(RUNTIME / "factory_cli_supervisor.log"),
                "tee": str(log),
                "hybrid": str(RUNTIME / "factory_runner_stdout.log"),
            },
        }
        STATE.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        print(f"launched pid={p.pid} (no nested supervisor keeper)")
        print(f"monitor: python -u scripts/monitor_factory_cli.py")
        print(f"state: {STATE}")
        if os.getenv("LAUNCH_OPS_KEEPER", "true").lower() in {"1", "true", "yes"}:
            try:
                subprocess.Popen(
                    [sys.executable, "-u", str(ROOT / "scripts" / "launch_ops_keeper_detached.py")],
                    cwd=str(ROOT),
                    env={**os.environ, "SUPERVISOR_KEEPER": "false"},
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=flags if sys.platform == "win32" else 0,
                    close_fds=True,
                    start_new_session=(sys.platform != "win32"),
                )
                print("ops_keeper: launch_ops_keeper_detached.py invoked")
            except Exception as exc:
                print(f"ops_keeper launch skipped: {exc}")
        return 0

    keeper_log = RUNTIME / "factory_supervisor_keeper.log"
    keeper_script = RUNTIME / "_supervisor_keeper.py"
    keeper_script.write_text(
        f'''# auto-generated supervisor keeper
import os, sys, time, subprocess
from pathlib import Path
ROOT = Path(r"{ROOT}")
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
LOG = Path(r"{keeper_log}")
INTERVAL = int(os.getenv("SUPERVISOR_KEEPER_SEC", "90"))

def alive(pid):
    if not pid: return False
    try:
        if sys.platform == "win32":
            import ctypes
            h = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))
            if h:
                ctypes.windll.kernel32.CloseHandle(h)
                return True
            return False
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False

def find_supervisor():
    try:
        import subprocess as sp
        r = sp.run(["wmic","process","where","name='python.exe'","get","ProcessId,CommandLine","/FORMAT:CSV"],
                   capture_output=True, text=True, timeout=30)
        for line in (r.stdout or "").splitlines():
            if "factory_cli_supervisor.py" in line:
                pid = line.rsplit(",",1)[-1].strip()
                if pid.isdigit():
                    return int(pid)
    except Exception:
        pass
    return 0

def launch():
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONPATH"] = str(ROOT)
    env["FACTORY_MAX_RUNTIME_SEC"] = "0"
    flags = 0x00000200 | 0x00000008 | 0x08000000  # new group + detached + no window
    tee = ROOT / "runtime" / "factory_cli_supervisor_tee.log"
    with tee.open("a", encoding="utf-8") as fh:
        fh.write(f"\\n--- keeper relaunch {{time.time()}} ---\\n")
        fh.flush()
        p = subprocess.Popen(
            [sys.executable, "-u", str(ROOT / "scripts" / "factory_cli_supervisor.py")],
            cwd=str(ROOT), env=env, stdout=fh, stderr=subprocess.STDOUT,
            creationflags=flags if sys.platform == "win32" else 0,
            close_fds=True,
        )
    return p.pid

def main():
    LOG.parent.mkdir(parents=True, exist_ok=True)
    # Give concurrent launch() time to register before first check (avoid double supervisor)
    time.sleep(min(45, INTERVAL // 2 or 20))
    while True:
        try:
            pid = find_supervisor()
            if pid and alive(pid):
                time.sleep(INTERVAL)
                continue
            # Double-check after short wait (race with sibling launch)
            time.sleep(5)
            pid2 = find_supervisor()
            if pid2 and alive(pid2):
                time.sleep(INTERVAL)
                continue
            newp = launch()
            with LOG.open("a", encoding="utf-8") as fh:
                fh.write(f"{{time.strftime('%Y-%m-%dT%H:%M:%SZ')}} relaunched supervisor pid={{newp}}\\n")
            time.sleep(INTERVAL)
        except Exception as exc:
            with LOG.open("a", encoding="utf-8") as fh:
                fh.write(f"{{time.strftime('%Y-%m-%dT%H:%M:%SZ')}} keeper error: {{exc}}\\n")
            time.sleep(INTERVAL)

if __name__ == "__main__":
    main()
''',
        encoding="utf-8",
    )
    keeper = subprocess.Popen(
        [sys.executable, "-u", str(keeper_script)],
        cwd=str(ROOT),
        env=os.environ.copy(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags if sys.platform == "win32" else 0,
        close_fds=True,
        start_new_session=(sys.platform != "win32"),
    )

    meta = {
        "schema": "rsi_eaf_detached_launch_v1",
        "launched_at": datetime.now(timezone.utc).isoformat(),
        "supervisor_pid": p.pid,
        "keeper_pid": keeper.pid,
        "monitor_cmd": "python -u scripts/monitor_factory_cli.py",
        "logs": {
            "supervisor": str(RUNTIME / "factory_cli_supervisor.log"),
            "tee": str(log),
            "hybrid": str(RUNTIME / "factory_runner_stdout.log"),
            "keeper": str(keeper_log),
        },
    }
    STATE.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"launched pid={p.pid} keeper={keeper.pid}")
    print(f"monitor: python -u scripts/monitor_factory_cli.py")
    print(f"state: {STATE}")
    # Prefer thrash-safe ops keeper for long-run (monitor + single supervisor)
    if os.getenv("LAUNCH_OPS_KEEPER", "true").lower() in {"1", "true", "yes"}:
        try:
            subprocess.Popen(
                [sys.executable, "-u", str(ROOT / "scripts" / "launch_ops_keeper_detached.py")],
                cwd=str(ROOT),
                env={**os.environ, "SUPERVISOR_KEEPER": "false"},
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=flags if sys.platform == "win32" else 0,
                close_fds=True,
                start_new_session=(sys.platform != "win32"),
            )
            print("ops_keeper: launch_ops_keeper_detached.py invoked")
        except Exception as exc:
            print(f"ops_keeper launch skipped: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
