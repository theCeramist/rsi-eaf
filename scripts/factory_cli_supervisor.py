#!/usr/bin/env python3
"""
Visible factory supervisor for Grok Build CLI.

Runs hybrid + x_daemon as *child* processes (not hidden/detached) and streams
their logs to stdout so the task appears as a live background job in the CLI.

This is the canonical "show me the factory is running" surface inside Grok Build:
  python -u scripts/factory_cli_supervisor.py

Env:
  SUPERVISOR_HEARTBEAT_SEC=30
  FACTORY_MAX_RUNTIME_SEC=0   (no 9h self-exit under supervisor)
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

RUNTIME = ROOT / "runtime"
LOCK = ROOT / "factory_core" / ".runner.lock"
STATE = RUNTIME / "factory_cli_supervisor_state.json"

HYBRID_SCRIPT = ROOT / "scripts" / "run_continuous_hybrid.py"
X_SCRIPT = ROOT / "observability" / "x_daemon.py"
HYBRID_LOG = RUNTIME / "factory_runner_stdout.log"
X_LOG = RUNTIME / "x_daemon_stdout.log"
SUP_LOG = RUNTIME / "factory_cli_supervisor.log"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(msg: str) -> None:
    line = f"[{_now()}] {msg}"
    print(line, flush=True)
    try:
        RUNTIME.mkdir(parents=True, exist_ok=True)
        with SUP_LOG.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def _clear_stale_lock() -> None:
    if not LOCK.exists():
        return
    try:
        raw = LOCK.read_text(encoding="utf-8").strip()
        pid = int(raw.split()[0]) if raw else 0
    except (OSError, ValueError):
        raw, pid = "", 0
    if pid and pid != os.getpid():
        # if lock pid not this process, drop it — we own the runner under supervisor
        try:
            LOCK.unlink(missing_ok=True)
            _log(f"cleared runner lock (was {raw!r})")
        except OSError as exc:
            _log(f"lock clear failed: {exc}")


def _child_env() -> dict:
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["FACTORY_CLI_SUPERVISOR"] = "1"
    env["FACTORY_PREFLIGHT_PYTEST"] = "false"
    env["FACTORY_RUN_CONTINUOUS"] = "true"
    # Force — do not inherit a stuck true from parent shell .env
    env["VERCEL_DEPLOY"] = "false"
    env["BEST_OF_N_ON_EVOLUTION"] = "false"
    env["GROK_PARALLEL_ANALYSIS"] = env.get("GROK_PARALLEL_ANALYSIS", "false")
    env["REVENUE_PURSUIT"] = "true"
    env["CYCLE_MODE"] = "hybrid"
    env["X_AGENT_DAEMON_ENABLED"] = "true"
    env["X_AGENT_SCOUT_MODE"] = env.get("X_AGENT_SCOUT_MODE", "callout")
    env["FACTORY_SKIP_TOOL_PHASE"] = env.get("FACTORY_SKIP_TOOL_PHASE", "true")
    env["ICP_HUNT_QUIET"] = "true"
    # Supervisor already owns x_daemon process — avoid nested x_agent thread in hybrid
    env["X_AGENT_DAEMON_ENABLED"] = "false"
    # No self-exit; supervisor restarts
    env["FACTORY_MAX_RUNTIME_SEC"] = "0"
    return env


def _pump(prefix: str, stream, log_path: Path) -> None:
    """Stream child lines to supervisor stdout + file."""
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8", errors="replace") as logf:
            for line in iter(stream.readline, ""):
                if not line:
                    break
                text = line.rstrip("\n")
                print(f"{prefix}{text}", flush=True)
                logf.write(line)
                logf.flush()
    except Exception as exc:
        print(f"{prefix}[pump-error] {exc}", flush=True)
    finally:
        try:
            stream.close()
        except Exception:
            pass


def _start_child(name: str, script: Path, log_path: Path) -> subprocess.Popen:
    _log(f"starting {name}: {script}")
    try:
        with log_path.open("a", encoding="utf-8", errors="replace") as lf:
            lf.write(f"\n--- {_now()} supervisor start {name} ---\n")
    except OSError:
        pass
    proc = subprocess.Popen(
        [sys.executable, "-u", str(script)],
        cwd=str(ROOT),
        env=_child_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        text=True,
        bufsize=1,
        # Visible tree: do NOT detach / hide window
    )
    prefix = f"[{name} pid={proc.pid}] "
    t = threading.Thread(
        target=_pump,
        args=(prefix, proc.stdout, log_path),
        name=f"pump-{name}",
        daemon=True,
    )
    t.start()
    _log(f"{name} live pid={proc.pid}")
    return proc


def _write_state(hybrid: subprocess.Popen | None, x_daemon: subprocess.Popen | None) -> None:
    import json

    payload = {
        "schema": "rsi_eaf_factory_cli_supervisor_v1",
        "updated_at": _now(),
        "supervisor_pid": os.getpid(),
        "visible_in": "grok_build_cli_background_task",
        "hybrid": {
            "pid": hybrid.pid if hybrid else None,
            "alive": hybrid.poll() is None if hybrid else False,
        },
        "x_daemon": {
            "pid": x_daemon.pid if x_daemon else None,
            "alive": x_daemon.poll() is None if x_daemon else False,
        },
    }
    RUNTIME.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> int:
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env", override=True)
    except Exception:
        pass

    heartbeat = float(os.getenv("SUPERVISOR_HEARTBEAT_SEC", "30"))
    _log(f"FACTORY CLI SUPERVISOR start pid={os.getpid()} root={ROOT}")
    _log("This process is the visible running indicator in Grok Build CLI.")
    _clear_stale_lock()

    hybrid: subprocess.Popen | None = None
    x_daemon: subprocess.Popen | None = None
    restarts = {"hybrid": 0, "x_daemon": 0}
    hybrid_started_mono: float | None = None
    plugin_tick = 0

    try:
        while True:
            if hybrid is None or hybrid.poll() is not None:
                code = hybrid.returncode if hybrid is not None else None
                if hybrid is not None:
                    _log(f"hybrid exited code={code} — restarting")
                    restarts["hybrid"] += 1
                    _clear_stale_lock()
                hybrid = _start_child("hybrid", HYBRID_SCRIPT, HYBRID_LOG)
                hybrid_started_mono = time.monotonic()

            if x_daemon is None or x_daemon.poll() is not None:
                code = x_daemon.returncode if x_daemon is not None else None
                if x_daemon is not None:
                    _log(f"x_daemon exited code={code} — restarting")
                    restarts["x_daemon"] += 1
                x_daemon = _start_child("x_daemon", X_SCRIPT, X_LOG)

            _write_state(hybrid, x_daemon)
            h_alive = hybrid.poll() is None
            x_alive = x_daemon.poll() is None

            # Blocker guardian — detect head-on, remediate, document (never hide)
            blockers_payload: dict = {}
            uptime_min = (
                (time.monotonic() - hybrid_started_mono) / 60.0
                if hybrid_started_mono is not None
                else 0.0
            )

            def _force_hybrid_restart() -> None:
                nonlocal hybrid, hybrid_started_mono
                if hybrid is not None and hybrid.poll() is None:
                    hybrid.terminate()
                    try:
                        hybrid.wait(timeout=12)
                    except Exception:
                        hybrid.kill()
                hybrid = None
                hybrid_started_mono = None
                _clear_stale_lock()

            def _force_x_restart() -> None:
                nonlocal x_daemon
                if x_daemon is not None and x_daemon.poll() is None:
                    x_daemon.terminate()
                    try:
                        x_daemon.wait(timeout=12)
                    except Exception:
                        x_daemon.kill()
                x_daemon = None

            try:
                from factory_core.blocker_guardian import run_guardian_pass

                blockers_payload = run_guardian_pass(
                    hybrid_pid=hybrid.pid if h_alive else None,
                    x_daemon_pid=x_daemon.pid if x_alive else None,
                    hybrid_uptime_min=uptime_min,
                    hybrid_restart=_force_hybrid_restart,
                    x_restart=_force_x_restart,
                )
                open_n = blockers_payload.get("open_count", 0)
                p0 = blockers_payload.get("p0_count", 0)
                ids = [b.get("id") for b in (blockers_payload.get("open_blockers") or [])]
                _log(
                    f"BLOCKERS open={open_n} p0={p0} ids={ids} "
                    f"(see observability/BLOCKER_RUNBOOK.md — nothing hidden)"
                )
                for b in blockers_payload.get("open_blockers") or []:
                    _log(
                        f"  OPEN [{b.get('severity')}] {b.get('id')}: {b.get('title')}"
                    )
                for rem in blockers_payload.get("remediations_this_pass") or []:
                    _log(
                        f"  REMEDIATE {rem.get('blocker_id')} success={rem.get('success')} "
                        f"{rem.get('status_after')}"
                    )
            except Exception as exc:
                _log(f"blocker_guardian error: {exc}")

            # Scoreboard + conversion integrity (never leave pay.html dead)
            # Re-sample after guardian may have nullified children
            h_alive = hybrid is not None and hybrid.poll() is None
            x_alive = x_daemon is not None and x_daemon.poll() is None
            score = {}
            try:
                from tools.factory_scoreboard import write_scoreboard

                score = write_scoreboard(
                    hybrid_pid=hybrid.pid if h_alive and hybrid is not None else None,
                    x_daemon_pid=x_daemon.pid if x_alive and x_daemon is not None else None,
                    supervisor_pid=os.getpid(),
                    blockers=blockers_payload,
                )
            except Exception as exc:
                score = {"error": str(exc)[:120]}
            try:
                from tools.conversion_surfaces import ensure_conversion_surfaces

                # only redeploy if broken — cheap when green
                ensure_conversion_surfaces(force_deploy=False)
            except Exception as exc:
                _log(f"conversion_guard error: {exc}")

            # Link watcher — every heartbeat (critical social CTA integrity)
            if os.getenv("LINK_WATCHER_ENABLED", "true").lower() in {"1", "true", "yes"}:
                try:
                    from tools.link_watcher import run_link_watcher

                    lw = run_link_watcher(remediate=True)
                    summ = lw.get("summary") or (lw.get("probe") or {}).get("summary") or {}
                    cta = lw.get("preferred_cta") or {}
                    _log(
                        f"LINK_WATCHER ok={summ.get('ok')}/{summ.get('total')} "
                        f"safe_to_post={summ.get('safe_to_post')} "
                        f"failed={summ.get('failed')} critical={summ.get('critical_failed')} "
                        f"cta_pay={(cta.get('pay') or '')[:60]}"
                    )
                    if not summ.get("safe_to_post"):
                        _log(
                            f"LINK_WATCHER BLOCK posts — failed={((lw.get('probe') or lw).get('failed_urls') or [])[:5]}"
                        )
                except Exception as exc:
                    _log(f"link_watcher error: {exc}")

            # Marketplace plugin stack — use vercel/exa/firecrawl/stripe/sentry/chrome/axiom/superpowers
            if os.getenv("PLUGIN_STACK_ENABLED", "true").lower() in {"1", "true", "yes"}:
                try:
                    plugin_tick += 1
                    every = max(1, int(os.getenv("PLUGIN_STACK_EVERY_N_HEARTBEATS", "5") or "5"))
                    if plugin_tick == 1 or plugin_tick % every == 0:
                        from tools.plugin_stack import run_plugin_stack

                        ps = run_plugin_stack(0, force=False)
                        summ = ps.get("summary") or {}
                        _log(
                            f"PLUGIN_STACK used={summ.get('plugins_used')} "
                            f"ok={summ.get('plugins_ok')} success={summ.get('success')} "
                            f"ms={summ.get('duration_ms')}"
                        )
                except Exception as exc:
                    _log(f"plugin_stack error: {exc}")

            # Guardian remediations may null hybrid/x_daemon — re-sample before logging
            h_alive = hybrid is not None and hybrid.poll() is None
            x_alive = x_daemon is not None and x_daemon.poll() is None
            h_pid = hybrid.pid if hybrid is not None else None
            x_pid = x_daemon.pid if x_daemon is not None else None

            org = score.get("organic_revenue_usd")
            conv = score.get("conversion") or {}
            pay_ok = conv.get("pay_ok") if "pay_ok" in conv else conv.get("all_ok")
            cycle = score.get("cycle_id")
            x_age = score.get("x_tick_age_min")
            open_n = (blockers_payload or {}).get("open_count", "?")
            _log(
                f"HEARTBEAT hybrid={'UP' if h_alive else 'DOWN'}(pid={h_pid}) "
                f"x_daemon={'UP' if x_alive else 'DOWN'}(pid={x_pid}) "
                f"cycle={cycle} organic=${org} pay_live={pay_ok} x_tick_age_min={x_age} "
                f"blockers_open={open_n} restarts={restarts}"
            )

            # Stuck hybrid: only after THIS process has been up long enough AND
            # no [Director]/[Cycle] progress in hybrid log / health still not advancing cycles.
            try:
                stuck_min = float(os.getenv("SUPERVISOR_HYBRID_STUCK_MIN", "50"))
                uptime_min = (
                    (time.monotonic() - hybrid_started_mono) / 60.0
                    if hybrid_started_mono is not None
                    else 0.0
                )
                # Detect log progress
                log_progress = False
                try:
                    tail = HYBRID_LOG.read_text(encoding="utf-8", errors="replace")[-8000:]
                    log_progress = any(
                        m in tail
                        for m in ("[Director]", "[Cycle]", "Cycle ", "Sleeping", "mode=")
                    )
                except OSError:
                    pass
                if (
                    h_alive
                    and hybrid is not None
                    and uptime_min >= stuck_min
                    and not log_progress
                ):
                    _log(
                        f"hybrid STUCK uptime_min={uptime_min:.1f} no cycle log markers — forcing restart"
                    )
                    hybrid.terminate()
                    try:
                        hybrid.wait(timeout=15)
                    except Exception:
                        hybrid.kill()
                    hybrid = None
                    hybrid_started_mono = None
                    restarts["hybrid"] = restarts.get("hybrid", 0) + 1
                    _clear_stale_lock()
            except Exception as exc:
                _log(f"stuck-check error: {exc}")

            time.sleep(max(10.0, heartbeat))
    except KeyboardInterrupt:
        _log("supervisor interrupt — stopping children")
        for p in (hybrid, x_daemon):
            if p and p.poll() is None:
                p.terminate()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
