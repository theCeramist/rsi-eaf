#!/usr/bin/env python3
"""
Thrash-safe factory ops keeper (Windows-first).

Keeps exactly one of each:
  - factory_cli_supervisor (owns hybrid + x_daemon)
  - monitor_factory_cli (extreme CLI stream)

Rules (anti-thrash):
  - Detect by live process command lines, never trust stale PID files alone
  - If count >= 1 for a role, do nothing (never double-launch)
  - Cooldown between relaunches (default 120s)
  - SUPERVISOR_KEEPER=false when spawning supervisor (no nested keepers)
  - Does NOT start hybrid/x directly — supervisor owns those

Usage:
  python -u scripts/factory_ops_keeper.py
  python -u scripts/factory_ops_keeper.py --once
  python -u scripts/factory_ops_keeper.py --interval 90

Env:
  OPS_KEEPER_INTERVAL_SEC=90
  OPS_KEEPER_COOLDOWN_SEC=120
  OPS_KEEPER_MONITOR=true
  OPS_KEEPER_SUPERVISOR=true
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
STATE = RUNTIME / "factory_ops_keeper_state.json"
LOG = RUNTIME / "factory_ops_keeper.log"

SUPERVISOR_MARKERS = ("factory_cli_supervisor.py", "scripts\\factory_cli_supervisor", "scripts/factory_cli_supervisor")
MONITOR_MARKERS = ("monitor_factory_cli.py", "scripts\\monitor_factory_cli", "scripts/monitor_factory_cli")
KEEPER_MARKERS = ("factory_ops_keeper.py", "scripts\\factory_ops_keeper", "scripts/factory_ops_keeper")
HYBRID_MARKERS = ("run_continuous_hybrid.py",)
X_MARKERS = ("x_daemon.py", "observability\\x_daemon", "observability/x_daemon")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(msg: str) -> None:
    line = f"[{_now()}] {msg}"
    print(line, flush=True)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


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


def _list_python_cmdlines() -> List[Tuple[int, str]]:
    results: List[Tuple[int, str]] = []
    if sys.platform == "win32":
        # Prefer PowerShell — wmic is removed on many Win11 builds
        try:
            ps = (
                "Get-CimInstance Win32_Process -Filter \"Name='python.exe' OR Name='pythonw.exe'\" | "
                "ForEach-Object { '{0}|{1}' -f $_.ProcessId, $_.CommandLine }"
            )
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps],
                capture_output=True,
                text=True,
                timeout=45,
            )
            for line in (r.stdout or "").splitlines():
                if "|" not in line:
                    continue
                pid_s, cmd = line.split("|", 1)
                try:
                    results.append((int(pid_s.strip()), cmd.strip()))
                except ValueError:
                    pass
        except (subprocess.SubprocessError, OSError) as exc:
            _log(f"powershell process list failed: {exc}")
        if not results:
            try:
                r = subprocess.run(
                    [
                        "wmic",
                        "process",
                        "where",
                        "name='python.exe' or name='pythonw.exe'",
                        "get",
                        "ProcessId,CommandLine",
                        "/FORMAT:CSV",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=45,
                    cwd=str(ROOT),
                )
                for line in (r.stdout or "").splitlines():
                    line = line.strip()
                    if not line or line.lower().startswith("node,") or "commandline" in line.lower():
                        continue
                    parts = line.rsplit(",", 1)
                    if len(parts) != 2:
                        continue
                    cmd, pid_s = parts[0], parts[1].strip()
                    if cmd.count(",") >= 1:
                        cmd = cmd.split(",", 1)[-1]
                    try:
                        pid = int(pid_s)
                    except ValueError:
                        continue
                    if pid > 0:
                        results.append((pid, cmd or ""))
            except (subprocess.SubprocessError, OSError, ValueError) as exc:
                _log(f"wmic list failed: {exc}")
    else:
        try:
            r = subprocess.run(["ps", "ax", "-o", "pid=,args="], capture_output=True, text=True, timeout=20)
            for line in (r.stdout or "").splitlines():
                line = line.strip()
                if not line:
                    continue
                parts = line.split(None, 1)
                if len(parts) != 2:
                    continue
                try:
                    results.append((int(parts[0]), parts[1]))
                except ValueError:
                    pass
        except (subprocess.SubprocessError, OSError):
            pass
    return results


def _find_pids(markers: Tuple[str, ...], procs: Optional[List[Tuple[int, str]]] = None) -> List[int]:
    procs = procs if procs is not None else _list_python_cmdlines()
    out: List[int] = []
    for pid, cmd in procs:
        low = (cmd or "").lower()
        # Don't count this keeper process as supervisor/monitor
        if any(m.lower() in low for m in KEEPER_MARKERS):
            continue
        if any(m.lower() in low for m in markers):
            out.append(pid)
    return out


def _win_flags() -> int:
    CREATE_NEW_PROCESS_GROUP = 0x00000200
    DETACHED_PROCESS = 0x00000008
    CREATE_NO_WINDOW = 0x08000000
    return CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS | CREATE_NO_WINDOW


def _child_env() -> Dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "PYTHONUNBUFFERED": "1",
            "PYTHONPATH": str(ROOT),
            "FACTORY_CLI_SUPERVISOR": "1",
            "FACTORY_MAX_RUNTIME_SEC": "0",
            "SUPERVISOR_KEEPER": "false",  # never nest thrash keepers
            "FACTORY_SKIP_TOOL_PHASE": env.get("FACTORY_SKIP_TOOL_PHASE", "true"),
            "FACTORY_PREFLIGHT_PYTEST": env.get("FACTORY_PREFLIGHT_PYTEST", "false"),
            "VERCEL_DEPLOY": env.get("VERCEL_DEPLOY", "false"),
            "X_AGENT_DAEMON_ENABLED": env.get("X_AGENT_DAEMON_ENABLED", "true"),
            "LINK_WATCHER_ENABLED": "true",
            "MAINNET_REVENUE_LANE": "true",
            "XRPL_NETWORK": env.get("XRPL_NETWORK", "dual"),
            "XRPL_OPS_NETWORK": env.get("XRPL_OPS_NETWORK", "testnet"),
            "XRPL_REVENUE_NETWORK": env.get("XRPL_REVENUE_NETWORK", "mainnet"),
            "MAINNET_OUTBOUND_ENABLED": env.get("MAINNET_OUTBOUND_ENABLED", "false"),
        }
    )
    return env


def _spawn(name: str, args: List[str], log_path: Path) -> int:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(f"\n--- {_now()} ops_keeper spawn {name} ---\n")
        fh.flush()
        kwargs = {
            "cwd": str(ROOT),
            "env": _child_env(),
            "stdout": fh,
            "stderr": subprocess.STDOUT,
            "stdin": subprocess.DEVNULL,
        }
        if sys.platform == "win32":
            kwargs["creationflags"] = _win_flags()
            kwargs["close_fds"] = True
        else:
            kwargs["start_new_session"] = True
            kwargs["close_fds"] = True
        p = subprocess.Popen([sys.executable, "-u", *args], **kwargs)
    return int(p.pid)


def _cooldown_ok(state: dict, role: str, cooldown_sec: float) -> bool:
    last = (state.get("last_launch") or {}).get(role)
    if not last:
        return True
    try:
        t = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - t).total_seconds()
        return age >= cooldown_sec
    except Exception:
        return True


def _mark_launch(state: dict, role: str, pid: int) -> None:
    state.setdefault("last_launch", {})[role] = _now()
    state.setdefault("pids", {})[role] = pid
    state.setdefault("restarts", {})
    state["restarts"][role] = int(state["restarts"].get(role) or 0) + 1


def _save(state: dict) -> None:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = _now()
    state["schema"] = "rsi_eaf_factory_ops_keeper_v1"
    STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def ensure_once(
    *,
    want_supervisor: bool = True,
    want_monitor: bool = True,
    cooldown_sec: float = 120.0,
) -> dict:
    os.chdir(ROOT)
    _load_dotenv()
    state: dict = {}
    if STATE.exists():
        try:
            state = json.loads(STATE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            state = {}

    procs = _list_python_cmdlines()
    sup = _find_pids(SUPERVISOR_MARKERS, procs)
    mon = _find_pids(MONITOR_MARKERS, procs)
    hybrid = _find_pids(HYBRID_MARKERS, procs)
    xdaemon = _find_pids(X_MARKERS, procs)
    keepers = _find_pids(KEEPER_MARKERS, procs)

    actions: List[dict] = []

    # Supervisor: only if zero live supervisors
    if want_supervisor:
        if len(sup) > 1:
            # Extra supervisors: do not kill (risky); log only
            _log(f"WARN multiple supervisors pids={sup} — not killing; thrash risk")
            actions.append({"role": "supervisor", "action": "skip_multi", "pids": sup})
        elif len(sup) == 1:
            actions.append({"role": "supervisor", "action": "ok", "pid": sup[0]})
        else:
            if not _cooldown_ok(state, "supervisor", cooldown_sec):
                actions.append({"role": "supervisor", "action": "cooldown"})
                _log("supervisor down but cooldown active")
            else:
                # Prefer launch_factory_detached with keeper disabled
                pid = _spawn(
                    "supervisor",
                    [
                        str(ROOT / "scripts" / "factory_cli_supervisor.py"),
                    ],
                    RUNTIME / "factory_cli_supervisor_tee.log",
                )
                _mark_launch(state, "supervisor", pid)
                actions.append({"role": "supervisor", "action": "launched", "pid": pid})
                _log(f"launched supervisor pid={pid}")
                time.sleep(3)
                # refresh
                procs = _list_python_cmdlines()
                sup = _find_pids(SUPERVISOR_MARKERS, procs)

    # Monitor: only if zero live monitors
    if want_monitor:
        if len(mon) >= 1:
            actions.append({"role": "monitor", "action": "ok", "pids": mon})
        else:
            if not _cooldown_ok(state, "monitor", cooldown_sec):
                actions.append({"role": "monitor", "action": "cooldown"})
                _log("monitor down but cooldown active")
            else:
                pid = _spawn(
                    "monitor",
                    [
                        str(ROOT / "scripts" / "monitor_factory_cli.py"),
                        "--detail",
                        "extreme",
                        "--interval",
                        "8",
                        "--jsonl",
                        "--history",
                        "50",
                    ],
                    RUNTIME / "factory_ops_monitor_tee.log",
                )
                _mark_launch(state, "monitor", pid)
                actions.append({"role": "monitor", "action": "launched", "pid": pid})
                _log(f"launched monitor pid={pid}")
                time.sleep(1)
                procs = _list_python_cmdlines()
                mon = _find_pids(MONITOR_MARKERS, procs)

    snapshot = {
        "supervisor_pids": sup,
        "monitor_pids": mon,
        "hybrid_pids": hybrid,
        "x_daemon_pids": xdaemon,
        "keeper_pids": keepers,
        "actions": actions,
        "at": _now(),
    }
    state["last_snapshot"] = snapshot
    _save(state)
    return snapshot


def main() -> int:
    ap = argparse.ArgumentParser(description="Thrash-safe factory ops keeper")
    ap.add_argument("--once", action="store_true", help="Single ensure pass then exit")
    ap.add_argument("--interval", type=float, default=float(os.getenv("OPS_KEEPER_INTERVAL_SEC", "90")))
    ap.add_argument("--cooldown", type=float, default=float(os.getenv("OPS_KEEPER_COOLDOWN_SEC", "120")))
    ap.add_argument("--no-monitor", action="store_true")
    ap.add_argument("--no-supervisor", action="store_true")
    args = ap.parse_args()

    want_mon = not args.no_monitor and os.getenv("OPS_KEEPER_MONITOR", "true").lower() in {
        "1",
        "true",
        "yes",
    }
    want_sup = not args.no_supervisor and os.getenv("OPS_KEEPER_SUPERVISOR", "true").lower() in {
        "1",
        "true",
        "yes",
    }

    _log(
        f"ops_keeper start once={args.once} interval={args.interval} cooldown={args.cooldown} "
        f"supervisor={want_sup} monitor={want_mon}"
    )

    if args.once:
        snap = ensure_once(
            want_supervisor=want_sup, want_monitor=want_mon, cooldown_sec=args.cooldown
        )
        print(json.dumps(snap, indent=2))
        return 0

    # Loop forever (detached process)
    while True:
        try:
            snap = ensure_once(
                want_supervisor=want_sup, want_monitor=want_mon, cooldown_sec=args.cooldown
            )
            _log(
                f"tick sup={snap.get('supervisor_pids')} mon={snap.get('monitor_pids')} "
                f"hybrid={snap.get('hybrid_pids')} x={snap.get('x_daemon_pids')} "
                f"actions={snap.get('actions')}"
            )
        except Exception as exc:
            _log(f"ensure error: {exc}")
        time.sleep(max(30.0, float(args.interval)))


if __name__ == "__main__":
    raise SystemExit(main())
