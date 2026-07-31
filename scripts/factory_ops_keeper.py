#!/usr/bin/env python3
"""
Thrash-safe factory ops keeper (Windows-first).

Keeps exactly one of each:
  - factory_cli_supervisor (owns hybrid + x_daemon)
  - monitor_factory_cli (extreme CLI stream)

Doctrine (non-negotiable):
  - Problems are confronted head-on — never "avoid" or soft-skip forever
  - Access Denied / dead children / multi-stacks are remediations, not footnotes
  - Escalate spawn path: CreateProcess flags → PowerShell Start-Process → cmd start
  - Record every failure to observability/ops_problems.json (OPEN until fixed)
  - Cooldown only after a verified-alive launch; dead PIDs always re-attempt
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
  OPS_SPAWN_TRY_BREAKAWAY=true   # try breakaway; on Access Denied escalate, do not hide
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
from typing import Any, Dict, List, Optional, Tuple

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
    looking_for_keeper = any(
        any(km.lower() in m.lower() for km in KEEPER_MARKERS) for m in markers
    )
    out: List[int] = []
    for pid, cmd in procs:
        low = (cmd or "").lower()
        # Don't count the ops keeper as supervisor/monitor/hybrid
        if not looking_for_keeper and any(m.lower() in low for m in KEEPER_MARKERS):
            continue
        # Don't count launch_ops_keeper wrapper as the loop keeper
        if looking_for_keeper and "launch_ops_keeper" in low:
            continue
        if any(m.lower() in low for m in markers):
            out.append(pid)
    return out


# Windows process creation flags
CREATE_NEW_PROCESS_GROUP = 0x00000200
DETACHED_PROCESS = 0x00000008
CREATE_NO_WINDOW = 0x08000000
CREATE_BREAKAWAY_FROM_JOB = 0x01000000

_SPAWN_FLAGS_CACHE = RUNTIME / "ops_spawn_flags.json"
_PROBLEMS_FILE = Path(os.getenv("OBSERVABILITY_DIR", "observability")) / "ops_problems.json"
_KNOWN_GOOD_FLAGS: Optional[int] = None
# Session memory of failed combos — still re-probed periodically (head-on, not forever-avoid)
_DENIED_FLAGS: Dict[int, str] = {}
_DENIED_REPROBE_SEC = 3600.0
_denied_at: Dict[int, float] = {}


def _record_problem(kind: str, detail: Dict[str, Any], *, resolved: bool = False) -> None:
    """Write/update an ops problem — OPEN until resolved. Never hide."""
    try:
        _PROBLEMS_FILE.parent.mkdir(parents=True, exist_ok=True)
        board: Dict[str, Any] = {"schema": "rsi_eaf_ops_problems_v1", "open": [], "resolved": []}
        if _PROBLEMS_FILE.exists():
            try:
                board = json.loads(_PROBLEMS_FILE.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        open_list: List[Dict[str, Any]] = list(board.get("open") or [])
        # upsert by kind
        open_list = [x for x in open_list if x.get("kind") != kind]
        rec = {
            "kind": kind,
            "status": "RESOLVED" if resolved else "OPEN",
            "updated_at": _now(),
            "detail": detail,
            "honesty": "problems_addressed_head_on",
        }
        if resolved:
            res = list(board.get("resolved") or [])
            res.append(rec)
            board["resolved"] = res[-50:]
        else:
            open_list.append(rec)
        board["open"] = open_list
        board["updated_at"] = _now()
        board["open_count"] = len(open_list)
        _PROBLEMS_FILE.write_text(json.dumps(board, indent=2, default=str), encoding="utf-8")
    except OSError as exc:
        _log(f"record_problem failed: {exc}")


def _win_flags_candidates() -> List[int]:
    """
    Ordered CreateProcess flags. We TRY breakaway (durability), and if Access Denied
    we record the problem and escalate to other launch mechanisms — we do not pretend
    the failure did not happen.
    """
    global _KNOWN_GOOD_FLAGS
    if _KNOWN_GOOD_FLAGS is None and _SPAWN_FLAGS_CACHE.exists():
        try:
            raw = json.loads(_SPAWN_FLAGS_CACHE.read_text(encoding="utf-8"))
            if isinstance(raw.get("flags"), int):
                _KNOWN_GOOD_FLAGS = int(raw["flags"])
        except (json.JSONDecodeError, OSError, TypeError, ValueError):
            pass

    base = CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
    candidates: List[int] = []
    if _KNOWN_GOOD_FLAGS is not None:
        candidates.append(_KNOWN_GOOD_FLAGS)

    # Full ladder — confront every combination, including breakaway
    candidates.extend(
        [
            base,  # known-good on this host
            base | DETACHED_PROCESS,
            CREATE_NEW_PROCESS_GROUP,
            DETACHED_PROCESS | CREATE_NO_WINDOW,
            base | CREATE_BREAKAWAY_FROM_JOB,  # head-on: try, remediate if denied
            base | CREATE_BREAKAWAY_FROM_JOB | DETACHED_PROCESS,
            0,
        ]
    )

    now = time.time()
    seen: set = set()
    out: List[int] = []
    for f in candidates:
        if f in seen:
            continue
        seen.add(f)
        # Re-probe denied flags after interval (do not avoid forever)
        if f in _DENIED_FLAGS:
            if now - _denied_at.get(f, 0) < _DENIED_REPROBE_SEC:
                continue
        out.append(f)
    return out


def _remember_good_flags(flags: int) -> None:
    global _KNOWN_GOOD_FLAGS
    _KNOWN_GOOD_FLAGS = int(flags)
    try:
        RUNTIME.mkdir(parents=True, exist_ok=True)
        _SPAWN_FLAGS_CACHE.write_text(
            json.dumps(
                {
                    "flags": int(flags),
                    "flags_hex": f"0x{int(flags):x}",
                    "updated_at": _now(),
                    "note": "Working CreateProcess flags after full ladder (including denied breakaway attempts)",
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        _record_problem(
            "windows_spawn_flags",
            {"flags": int(flags), "flags_hex": f"0x{int(flags):x}", "method": "CreateProcess"},
            resolved=True,
        )
    except OSError:
        pass


def _pid_alive(pid: int) -> bool:
    if not pid or int(pid) <= 0:
        return False
    if sys.platform == "win32":
        try:
            import ctypes

            k = ctypes.windll.kernel32
            h = k.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
            if h:
                k.CloseHandle(h)
                return True
            return False
        except Exception:
            return False
    try:
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False


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


def _spawn_via_powershell(name: str, args: List[str], log_path: Path) -> int:
    """Escalate after CreateProcess issues — Start-Process head-on."""
    arg_list = ["-u"] + [str(a) for a in args]
    arg_ps = ",".join("'" + a.replace("'", "''") + "'" for a in arg_list)
    py = str(sys.executable).replace("'", "''")
    wd = str(ROOT).replace("'", "''")
    ps = (
        f"$p = Start-Process -FilePath '{py}' "
        f"-ArgumentList {arg_ps} "
        f"-WorkingDirectory '{wd}' -WindowStyle Hidden -PassThru; "
        f"Write-Output $p.Id"
    )
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(ROOT),
            env=_child_env(),
        )
        for line in (r.stdout or "").splitlines():
            line = line.strip()
            if line.isdigit():
                pid = int(line)
                time.sleep(1.5)
                if _pid_alive(pid):
                    _log(f"spawn {name} ok via PowerShell Start-Process pid={pid}")
                    _record_problem(
                        "windows_spawn_access_denied",
                        {"method": "powershell_start_process", "pid": pid, "name": name},
                        resolved=True,
                    )
                    return pid
        _log(f"spawn {name} PowerShell failed rc={r.returncode} out={(r.stdout or '')[:200]}")
    except Exception as exc:
        _log(f"spawn {name} PowerShell escalate error: {exc}")
    return 0


def _spawn_via_cmd_start(name: str, args: List[str], log_path: Path) -> int:
    """Escalate: cmd start in new window group — head-on durability path."""
    runner = RUNTIME / f"_spawn_{name}.cmd"
    py = sys.executable
    script_args = " ".join(f'"{a}"' for a in args)
    runner.write_text(
        "\r\n".join(
            [
                "@echo off",
                f'cd /d "{ROOT}"',
                "set PYTHONUNBUFFERED=1",
                f'set PYTHONPATH={ROOT}',
                f'set FACTORY_MAX_RUNTIME_SEC=0',
                f'set SUPERVISOR_KEEPER=false',
                f'"{py}" -u {script_args} >> "{log_path}" 2>&1',
                "",
            ]
        ),
        encoding="utf-8",
    )
    try:
        subprocess.Popen(
            ["cmd.exe", "/c", "start", f"rsi-eaf-{name}", "/MIN", str(runner)],
            cwd=str(ROOT),
            env=_child_env(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW,
            close_fds=True,
        )
        time.sleep(2.5)
        # Find by markers
        markers = SUPERVISOR_MARKERS if "supervisor" in name else MONITOR_MARKERS
        pids = _find_pids(markers)
        for pid in pids:
            if _pid_alive(pid):
                _log(f"spawn {name} ok via cmd/start pid={pid}")
                _record_problem(
                    "windows_spawn_access_denied",
                    {"method": "cmd_start", "pid": pid, "name": name},
                    resolved=True,
                )
                return pid
        _log(f"spawn {name} cmd/start launched but process not found")
    except Exception as exc:
        _log(f"spawn {name} cmd/start escalate error: {exc}")
    return 0


def _spawn(name: str, args: List[str], log_path: Path) -> int:
    """
    Spawn durable child — full remediation ladder.

    1) CreateProcess flag ladder (including breakaway — record Access Denied)
    2) PowerShell Start-Process
    3) cmd /c start runner.cmd

    Never silent-fail. Returns pid or 0 only after all paths exhausted.
    """
    RUNTIME.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = _child_env()
    cmd = [sys.executable, "-u", *args]
    access_denied_hits: List[Dict[str, Any]] = []

    def _popen(flags: Optional[int]) -> int:
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(f"\n--- {_now()} ops_keeper spawn {name} flags={flags!r} ---\n")
            fh.flush()
            kwargs: Dict[str, Any] = {
                "cwd": str(ROOT),
                "env": env,
                "stdout": fh,
                "stderr": subprocess.STDOUT,
                "stdin": subprocess.DEVNULL,
            }
            if sys.platform == "win32":
                if flags is not None:
                    kwargs["creationflags"] = int(flags)
                kwargs["close_fds"] = True
            else:
                kwargs["start_new_session"] = True
                kwargs["close_fds"] = True
            p = subprocess.Popen(cmd, **kwargs)
            return int(p.pid)

    if sys.platform != "win32":
        pid = _popen(None)
        time.sleep(1.5)
        return pid if _pid_alive(pid) else 0

    # --- Path 1: CreateProcess flag ladder ---
    for flags in _win_flags_candidates():
        try:
            pid = _popen(flags)
        except OSError as exc:
            winerr = getattr(exc, "winerror", None)
            if winerr == 5 or "access is denied" in str(exc).lower():
                _DENIED_FLAGS[int(flags)] = str(exc)[:200]
                _denied_at[int(flags)] = time.time()
                access_denied_hits.append(
                    {
                        "flags": int(flags),
                        "flags_hex": f"0x{int(flags):x}",
                        "error": str(exc)[:200],
                        "winerror": winerr,
                    }
                )
                _log(
                    f"spawn {name} flags=0x{int(flags):x} Access Denied — "
                    f"recording OPEN problem, escalating other methods"
                )
                _record_problem(
                    "windows_spawn_access_denied",
                    {
                        "name": name,
                        "flags_hex": f"0x{int(flags):x}",
                        "error": str(exc)[:200],
                        "action": "escalate_powershell_and_cmd_start",
                        "hits": access_denied_hits[-5:],
                    },
                    resolved=False,
                )
            else:
                _log(f"spawn {name} flags=0x{int(flags):x} failed: {exc}")
            continue
        time.sleep(1.5)
        if _pid_alive(pid):
            _remember_good_flags(int(flags))
            _log(f"spawn {name} ok pid={pid} flags=0x{int(flags):x}")
            return pid
        _log(f"spawn {name} died immediately pid={pid} flags=0x{int(flags):x}")
        _record_problem(
            "windows_spawn_immediate_death",
            {"name": name, "pid": pid, "flags_hex": f"0x{int(flags):x}"},
            resolved=False,
        )

    # --- Path 2: PowerShell Start-Process (head-on after CreateProcess issues) ---
    _log(f"spawn {name}: CreateProcess ladder exhausted — escalating PowerShell")
    pid = _spawn_via_powershell(name, args, log_path)
    if pid:
        return pid

    # --- Path 3: cmd start ---
    _log(f"spawn {name}: PowerShell failed — escalating cmd/start")
    pid = _spawn_via_cmd_start(name, args, log_path)
    if pid:
        return pid

    _record_problem(
        "windows_spawn_total_failure",
        {
            "name": name,
            "args": [str(a) for a in args],
            "access_denied_hits": access_denied_hits,
            "action_required": "Check antivirus / Controlled Folder Access / Job Object; Task Scheduler Ensure still runs",
        },
        resolved=False,
    )
    _log(f"spawn {name}: ALL paths failed — OPEN ops problem recorded")
    return 0


def _remediate_multi_supervisors(sup_pids: List[int]) -> Dict[str, Any]:
    """
    Head-on: keep one supervisor (prefer one with hybrid alive), terminate extras.
    """
    if len(sup_pids) <= 1:
        return {"action": "none", "pids": sup_pids}
    keep = max(sup_pids)  # prefer newest stack
    killed: List[int] = []
    for pid in sup_pids:
        if pid == keep:
            continue
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                text=True,
                timeout=20,
            )
            killed.append(pid)
            _log(f"multi-supervisor remediated: killed extra pid={pid} kept={keep}")
        except Exception as exc:
            _log(f"multi-supervisor kill failed pid={pid}: {exc}")
    _record_problem(
        "multi_supervisor",
        {"kept": keep, "killed": killed, "was": sup_pids},
        resolved=bool(killed),
    )
    return {"action": "culled", "kept": keep, "killed": killed}


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
            # Head-on: cull extras (keep one)
            rem = _remediate_multi_supervisors(sup)
            actions.append({"role": "supervisor", "action": "remediate_multi", **rem})
            time.sleep(1)
            procs = _list_python_cmdlines()
            sup = _find_pids(SUPERVISOR_MARKERS, procs)
        if len(sup) == 1:
            actions.append({"role": "supervisor", "action": "ok", "pid": sup[0]})
            _record_problem("supervisor_down", {"pid": sup[0]}, resolved=True)
        elif len(sup) == 0:
            last_pid = int((state.get("pids") or {}).get("supervisor") or 0)
            # Waive cooldown if last launch PID is dead (failed spawn must not block recovery)
            waive = bool(last_pid and not _pid_alive(last_pid)) or last_pid == 0
            if not _cooldown_ok(state, "supervisor", cooldown_sec) and not waive:
                # Still address: record OPEN that we are cooldown-blocked but will re-try next pass
                actions.append({"role": "supervisor", "action": "cooldown_pending_retry", "next_sec": cooldown_sec})
                _log("supervisor down — cooldown pending (will re-attempt; problem OPEN)")
                _record_problem(
                    "supervisor_down",
                    {"status": "cooldown_pending", "last_pid": last_pid},
                    resolved=False,
                )
            else:
                if waive and not _cooldown_ok(state, "supervisor", cooldown_sec):
                    _log(f"supervisor cooldown waived — last pid {last_pid} dead or missing")
                pid = _spawn(
                    "supervisor",
                    [str(ROOT / "scripts" / "factory_cli_supervisor.py")],
                    RUNTIME / "factory_cli_supervisor_tee.log",
                )
                if pid and _pid_alive(pid):
                    _mark_launch(state, "supervisor", pid)
                    actions.append({"role": "supervisor", "action": "launched", "pid": pid})
                    _log(f"launched supervisor pid={pid}")
                    _record_problem("supervisor_down", {"pid": pid}, resolved=True)
                else:
                    actions.append({"role": "supervisor", "action": "spawn_failed", "pid": pid})
                    _log("supervisor spawn failed — OPEN; ladder exhausted")
                    _record_problem(
                        "supervisor_down",
                        {"status": "spawn_failed", "pid": pid},
                        resolved=False,
                    )
                time.sleep(2)
                procs = _list_python_cmdlines()
                sup = _find_pids(SUPERVISOR_MARKERS, procs)

    # Monitor: only if zero live monitors
    if want_monitor:
        if len(mon) > 1:
            # Keep newest monitor, kill extras
            keep = max(mon)
            killed = []
            for pid in mon:
                if pid == keep:
                    continue
                try:
                    subprocess.run(
                        ["taskkill", "/PID", str(pid), "/F"],
                        capture_output=True,
                        timeout=15,
                    )
                    killed.append(pid)
                except Exception:
                    pass
            actions.append({"role": "monitor", "action": "remediate_multi", "kept": keep, "killed": killed})
            mon = [keep] if _pid_alive(keep) else []
        if len(mon) >= 1:
            actions.append({"role": "monitor", "action": "ok", "pids": mon})
            _record_problem("monitor_down", {"pids": mon}, resolved=True)
        else:
            last_pid = int((state.get("pids") or {}).get("monitor") or 0)
            waive = bool(last_pid and not _pid_alive(last_pid)) or last_pid == 0
            if not _cooldown_ok(state, "monitor", cooldown_sec) and not waive:
                actions.append({"role": "monitor", "action": "cooldown_pending_retry"})
                _log("monitor down — cooldown pending (problem OPEN)")
                _record_problem("monitor_down", {"status": "cooldown_pending"}, resolved=False)
            else:
                if waive and not _cooldown_ok(state, "monitor", cooldown_sec):
                    _log(f"monitor cooldown waived — last pid {last_pid} dead or missing")
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
                if pid and _pid_alive(pid):
                    _mark_launch(state, "monitor", pid)
                    actions.append({"role": "monitor", "action": "launched", "pid": pid})
                    _log(f"launched monitor pid={pid}")
                    _record_problem("monitor_down", {"pid": pid}, resolved=True)
                else:
                    actions.append({"role": "monitor", "action": "spawn_failed", "pid": pid})
                    _log("monitor spawn failed — OPEN; ladder exhausted")
                    _record_problem("monitor_down", {"status": "spawn_failed", "pid": pid}, resolved=False)
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
