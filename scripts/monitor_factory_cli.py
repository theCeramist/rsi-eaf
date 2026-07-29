#!/usr/bin/env python3
"""
Extremely detailed CLI monitor for the detached RSI-EAF factory.

Streams factory *actions* into this Grok CLI session while the supervisor
runs outside the session Job Object.

Sources (followed live):
  runtime/factory_cli_supervisor.log
  runtime/factory_cli_supervisor_tee.log
  runtime/factory_runner_stdout.log   (hybrid cycles — full detail)
  runtime/x_daemon_stdout.log
  observability/*.jsonl               (new events: ledger, X, blockers, links, …)
  observability/factory_scoreboard.json / factory_health.json / blocker_status.json
  published/link-health.json

Usage:
  python -u scripts/monitor_factory_cli.py
  python -u scripts/monitor_factory_cli.py --detail extreme --interval 8
  python -u scripts/monitor_factory_cli.py --once

Env:
  MONITOR_INTERVAL_SEC=8
  MONITOR_DETAIL=extreme|full|actions|minimal
  MONITOR_JSONL=true
  MONITOR_ALL_LOG_LINES=true   # default true in extreme
  MONITOR_FOLLOW_LINES=80
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
OBS = ROOT / "observability"
PUB = ROOT / "published"

STATE = RUNTIME / "factory_cli_supervisor_state.json"
DETACHED = RUNTIME / "factory_detached_launch.json"
SUP_LOG = RUNTIME / "factory_cli_supervisor.log"
TEE_LOG = RUNTIME / "factory_cli_supervisor_tee.log"
HYBRID_LOG = RUNTIME / "factory_runner_stdout.log"
X_LOG = RUNTIME / "x_daemon_stdout.log"
LINK_HEALTH = PUB / "link-health.json"
SCOREBOARD = OBS / "factory_scoreboard.json"
HEALTH = OBS / "factory_health.json"
BLOCKERS = OBS / "blocker_status.json"
MAINNET = OBS / "mainnet_readiness.json"
LINK_LATEST = OBS / "link_watcher_latest.json"

# JSONL action streams (basename → short tag)
JSONL_STREAMS: List[Tuple[str, Path]] = [
    ("cycle", OBS / "cycle_traces.jsonl"),
    ("ledger", OBS / "economic_ledger.jsonl"),
    ("x_agent", OBS / "x_agent.jsonl"),
    ("blockers", OBS / "blocker_guardian.jsonl"),
    ("links", OBS / "link_watcher.jsonl"),
    ("outreach", OBS / "autonomous_outreach.jsonl"),
    ("dist", OBS / "distribution_daemon.jsonl"),
    ("xrpl_intel", OBS / "xrpl_intel.jsonl"),
    ("coord", OBS / "coordination_bus.jsonl"),
    ("critic", OBS / "critic_arena.jsonl"),
    ("sprint", OBS / "revenue_sprint.jsonl"),
    ("social", OBS / "social_learning.jsonl"),
    ("fail", OBS / "failure_lessons.jsonl"),
    ("ci", OBS / "ci_babysitter.jsonl"),
    ("conv", OBS / "conversion_surfaces.jsonl"),
    ("phase", OBS / "phase_innovation.jsonl"),
    ("intuit", OBS / "creative_intuition.jsonl"),
    ("xrpl_ai", OBS / "xrpl_ai_hub.jsonl"),
    ("payer", OBS / "payer_capture_daemon.jsonl"),
    ("acp", OBS / "acp_lane.jsonl"),
]

# Always show these even in "actions" mode
ACTION_LINE = re.compile(
    r"HEARTBEAT|LINK_WATCHER|BLOCKERS|OPEN \[|REMEDIATE|FACTORY CLI SUPERVISOR|"
    r"hybrid live|x_daemon live|\[RSI-EAF|Starting Cycle|Complete\.|GATE|"
    r"Payment SUCCESS|Payment FAILED|Preparing Payment|Memo:|"
    r"Phase \d|\[Cycle\]|\[Director\]|\[LinkWatcher\]|\[Treasury|"
    r"\[XRPL|\[AutonomousRunner\]|\[ToolImprover\]|\[Dreams\]|"
    r"\[FailureLearning\]|\[Coordination\]|\[Dashboard\]|"
    r"Daemon |LIKE |FOLLOW |broadcast|scout|icp_hunt|"
    r"error|ERROR|Traceback|Exception|VERCEL|deploy|Publish|ingest|"
    r"organic|revenue|gate |Verify|Evolve|Execute|Analyze|Propose",
    re.I,
)

NOISE_LINE = re.compile(r"^\s*$|^\s*={5,}\s*$")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _pid_alive(pid: Optional[int]) -> bool:
    if not pid:
        return False
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            handle = kernel32.OpenProcess(0x1000, 0, pid)
            if handle:
                kernel32.CloseHandle(handle)
                return True
            return False
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _find_factory_procs() -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {
        "supervisor": [],
        "hybrid": [],
        "x_daemon": [],
    }
    state = _read_json(STATE)
    det = _read_json(DETACHED)

    def add(kind: str, pid: Any, src: str) -> None:
        try:
            p = int(pid)
        except (TypeError, ValueError):
            return
        if not _pid_alive(p):
            return
        if any(x.get("pid") == p for x in out[kind]):
            return
        out[kind].append({"pid": p, "src": src})

    add("supervisor", state.get("supervisor_pid"), "state")
    hy = state.get("hybrid") or {}
    xd = state.get("x_daemon") or {}
    add("hybrid", hy.get("pid"), "state")
    add("x_daemon", xd.get("pid"), "state")
    add("supervisor", det.get("supervisor_pid"), "detached")

    try:
        import subprocess

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
            timeout=12,
            cwd=str(ROOT),
        )
        for line in (r.stdout or "").splitlines():
            low = line.lower()
            parts = line.split(",")
            if len(parts) < 2:
                continue
            try:
                pid = int(parts[-1].strip())
            except ValueError:
                continue
            cmd = ",".join(parts[1:-1])[:140]
            if "factory_cli_supervisor" in low:
                add("supervisor", pid, cmd)
            elif "run_continuous_hybrid" in low:
                add("hybrid", pid, cmd)
            elif "x_daemon" in low:
                add("x_daemon", pid, cmd)
    except Exception as exc:
        out["scan_note"] = str(exc)[:120]  # type: ignore[assignment]

    updated = state.get("updated_at")
    if updated and not out["supervisor"] and state.get("supervisor_pid"):
        try:
            t = datetime.fromisoformat(str(updated).replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - t).total_seconds()
            if age < 180:
                out["supervisor"].append(
                    {"pid": state.get("supervisor_pid"), "src": f"state_age={int(age)}s"}
                )
                if hy.get("pid"):
                    out["hybrid"].append({"pid": hy.get("pid"), "src": "state_age"})
                if xd.get("pid"):
                    out["x_daemon"].append({"pid": xd.get("pid"), "src": "state_age"})
        except Exception:
            pass
    return out


def _file_offset(path: Path) -> int:
    try:
        return path.stat().st_size if path.is_file() else 0
    except OSError:
        return 0


def _read_new(path: Path, offset: int) -> Tuple[str, int]:
    if not path.is_file():
        return "", offset
    try:
        size = path.stat().st_size
        if size < offset:
            offset = 0
        with path.open("rb") as fh:
            fh.seek(offset)
            data = fh.read()
        return data.decode("utf-8", errors="replace"), size
    except OSError:
        return "", offset


def _tail_text(path: Path, n: int = 80) -> List[str]:
    if not path.is_file():
        return []
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
    except OSError:
        return []


def _tail_jsonl(path: Path, n: int = 5) -> List[Dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        out: List[Dict[str, Any]] = []
        for line in lines[-n:]:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                out.append({"raw": line[:400]})
        return out
    except OSError:
        return []


def _fmt_json_event(tag: str, obj: Dict[str, Any], detail: str) -> str:
    """Compact but rich one-line summary of a JSONL event."""
    keys_pref = (
        "cycle_id",
        "event_type",
        "type",
        "phase",
        "source",
        "gate",
        "passed",
        "success",
        "op",
        "action",
        "blocker_id",
        "severity",
        "title",
        "tx_hash",
        "xrpl_tx_hash",
        "amount_usd_est",
        "network",
        "treasury_address",
        "live_url",
        "url",
        "status",
        "error",
        "focus",
        "mode",
        "summary",
        "safe_to_post",
        "failed",
        "ok",
        "total",
        "organic",
        "notes",
        "product_id",
        "destination_tag",
        "from_address",
        "verification_method",
        "revenue_class",
    )
    bits: List[str] = []
    for k in keys_pref:
        if k not in obj:
            continue
        v = obj[k]
        if v is None or v == "" or v == [] or v == {}:
            continue
        if isinstance(v, dict):
            # nested summary
            if k == "summary":
                bits.append(
                    "sum={"
                    + ",".join(f"{sk}:{sv}" for sk, sv in list(v.items())[:8])
                    + "}"
                )
            else:
                bits.append(f"{k}=…")
            continue
        s = str(v)
        if len(s) > 120:
            s = s[:117] + "…"
        bits.append(f"{k}={s}")
    # metadata flatten
    meta = obj.get("metadata") if isinstance(obj.get("metadata"), dict) else {}
    if meta:
        for k in ("notes", "live_url", "network", "product_id", "destination_tag", "xrp_received"):
            if k in meta and meta[k] is not None:
                s = str(meta[k])
                if len(s) > 80:
                    s = s[:77] + "…"
                bits.append(f"m.{k}={s}")
    if not bits:
        raw = json.dumps(obj, default=str)
        bits.append(raw[:220] + ("…" if len(raw) > 220 else ""))
    return f"[{tag}] " + " | ".join(bits[:18])


def snapshot(detail: str = "extreme") -> Dict[str, Any]:
    state = _read_json(STATE)
    score = _read_json(SCOREBOARD)
    link = _read_json(LINK_HEALTH)
    link_full = _read_json(LINK_LATEST)
    health = _read_json(HEALTH)
    blockers = _read_json(BLOCKERS)
    mainnet = _read_json(MAINNET)
    procs = _find_factory_procs()
    sup_alive = bool(procs.get("supervisor"))
    hybrid_alive = bool(procs.get("hybrid"))
    x_alive = bool(procs.get("x_daemon"))

    open_b = blockers.get("open_blockers") or blockers.get("open") or []
    if not open_b and isinstance(blockers.get("blockers"), list):
        open_b = [b for b in blockers["blockers"] if b.get("status") == "OPEN" or b.get("open")]

    return {
        "ts": _now_iso(),
        "procs": {
            "supervisor": [p["pid"] for p in procs.get("supervisor") or []],
            "hybrid": [p["pid"] for p in procs.get("hybrid") or []],
            "x_daemon": [p["pid"] for p in procs.get("x_daemon") or []],
            "alive": {
                "supervisor": sup_alive,
                "hybrid": hybrid_alive,
                "x_daemon": x_alive,
            },
            "detail": procs,
        },
        "state_file": state,
        "scoreboard": score,
        "health": health,
        "blockers": {
            "open_count": blockers.get("open_count", len(open_b)),
            "p0_count": blockers.get("p0_count"),
            "open": open_b[:12],
            "updated_at": blockers.get("updated_at") or blockers.get("ts"),
        },
        "link_health": link,
        "link_watcher": {
            "summary": (link_full.get("summary") or (link_full.get("probe") or {}).get("summary")),
            "preferred_cta": link_full.get("preferred_cta") or link.get("preferred_cta"),
            "failed_urls": (link_full.get("probe") or link_full).get("failed_urls")
            or link.get("failed_urls")
            or [],
            "critical_failed_urls": (link_full.get("probe") or link_full).get(
                "critical_failed_urls"
            )
            or link.get("critical_failed_urls")
            or [],
        },
        "mainnet": {
            "public_treasury": mainnet.get("public_treasury"),
            "public_network": mainnet.get("public_network"),
            "ready": (mainnet.get("ready_accept_unfunded") or {}).get("ready"),
            "activated": (mainnet.get("ready_strict_activated") or {})
            .get("checks", {})
            .get("account_activated"),
            "safety": mainnet.get("safety"),
        },
        "overall": (
            "UP"
            if sup_alive and hybrid_alive
            else ("PARTIAL" if sup_alive or hybrid_alive else "DOWN")
        ),
        "detail": detail,
    }


def print_banner(msg: str) -> None:
    print(f"\n[{_now()}] ══ {msg} ══", flush=True)


def print_snapshot(snap: Dict[str, Any], detail: str) -> None:
    p = snap["procs"]
    score = snap.get("scoreboard") or {}
    sb = score.get("scoreboard") or score
    link = snap.get("link_health") or {}
    lw = snap.get("link_watcher") or {}
    bl = snap.get("blockers") or {}
    mn = snap.get("mainnet") or {}
    health = snap.get("health") or {}

    print_banner("FACTORY STATUS")
    print(
        f"[{_now()}] overall={snap['overall']} "
        f"sup={p['supervisor'] or '-'} hybrid={p['hybrid'] or '-'} x={p['x_daemon'] or '-'}",
        flush=True,
    )
    print(
        f"[{_now()}] cycle={score.get('cycle_id') or health.get('cycle_id')} "
        f"verdict={score.get('verdict')} "
        f"organic=${sb.get('organic_revenue_usd') or score.get('organic_revenue_usd')} "
        f"revenue=${sb.get('total_revenue_usd') or score.get('total_revenue_usd')} "
        f"net=${sb.get('net_usd') or score.get('net_usd')} "
        f"pay_ok={(score.get('conversion') or {}).get('pay_ok') or (score.get('conversion') or {}).get('all_ok')}",
        flush=True,
    )
    print(
        f"[{_now()}] links safe_to_post={link.get('safe_to_post')} "
        f"ok={link.get('ok')} failed={link.get('failed')} "
        f"cta={((lw.get('preferred_cta') or link.get('preferred_cta') or {}) if isinstance(lw.get('preferred_cta') or link.get('preferred_cta'), dict) else {'pay': lw.get('preferred_cta') or link.get('preferred_cta')}).get('pay')}",
        flush=True,
    )
    print(
        f"[{_now()}] mainnet treasury={mn.get('public_treasury')} "
        f"network={mn.get('public_network')} ready={mn.get('ready')} "
        f"activated={mn.get('activated')} outbound={((mn.get('safety') or {}).get('mainnet_outbound_enabled'))}",
        flush=True,
    )
    print(
        f"[{_now()}] blockers open={bl.get('open_count')} p0={bl.get('p0_count')}",
        flush=True,
    )

    if detail in {"full", "extreme"}:
        for b in bl.get("open") or []:
            if isinstance(b, dict):
                print(
                    f"[{_now()}]   BLOCKER [{b.get('severity')}] {b.get('id')}: {b.get('title')}",
                    flush=True,
                )
                if detail == "extreme" and b.get("evidence"):
                    ev = json.dumps(b.get("evidence"), default=str)
                    print(f"[{_now()}]     evidence={ev[:300]}", flush=True)
                if detail == "extreme" and b.get("remediation"):
                    print(f"[{_now()}]     remediation={b.get('remediation')}", flush=True)

        failed = lw.get("failed_urls") or link.get("failed_urls") or []
        if failed:
            print(f"[{_now()}] link failures ({len(failed)}):", flush=True)
            for u in failed[:25]:
                print(f"[{_now()}]   FAIL {u}", flush=True)

        # Health keys of interest
        if health and detail == "extreme":
            interesting_h = {
                k: health[k]
                for k in (
                    "cycle_id",
                    "status",
                    "updated_at",
                    "mode",
                    "focus",
                    "runner",
                    "last_error",
                    "gates_passed",
                    "gates_failed",
                )
                if k in health
            }
            if interesting_h:
                print(
                    f"[{_now()}] health={json.dumps(interesting_h, default=str)[:500]}",
                    flush=True,
                )

        # Conversion detail
        conv = score.get("conversion") or {}
        if conv and detail == "extreme":
            print(
                f"[{_now()}] conversion={json.dumps(conv, default=str)[:500]}",
                flush=True,
            )

        # X surface
        xinfo = score.get("x") or {}
        if xinfo and detail == "extreme":
            print(
                f"[{_now()}] x_agent tick_age={score.get('x_tick_age_min')} "
                f"path={xinfo.get('path')} metrics={json.dumps(xinfo.get('metrics') or xinfo.get('totals') or {}, default=str)[:240]}",
                flush=True,
            )


def should_emit_log_line(line: str, detail: str, all_lines: bool) -> bool:
    if NOISE_LINE.match(line):
        return False
    if all_lines or detail == "extreme":
        return True
    if detail in {"full", "actions"}:
        return bool(ACTION_LINE.search(line))
    return bool(ACTION_LINE.search(line))


def emit_log(tag: str, line: str) -> None:
    # Preserve hybrid indentation content but prefix for multi-source
    print(f"[{tag}] {line}", flush=True)


def emit_jsonl_new(
    tag: str,
    path: Path,
    offset: int,
    detail: str,
) -> int:
    chunk, new_off = _read_new(path, offset)
    if not chunk:
        return new_off
    for line in chunk.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            if detail == "extreme":
                print(f"[{tag}] RAW {line[:300]}", flush=True)
            continue
        if not isinstance(obj, dict):
            continue
        print(f"[{_now()}] {_fmt_json_event(tag, obj, detail)}", flush=True)
        if detail == "extreme":
            # dump extra keys not already summarized
            extra = {
                k: v
                for k, v in obj.items()
                if k
                not in {
                    "cycle_id",
                    "event_type",
                    "type",
                    "phase",
                    "source",
                    "metadata",
                    "timestamp",
                    "ts",
                    "at",
                    "amount_usd_est",
                    "xrpl_tx_hash",
                    "tx_hash",
                }
                and v not in (None, "", [], {})
            }
            if extra:
                dump = json.dumps(extra, default=str)
                if len(dump) > 400:
                    dump = dump[:397] + "…"
                print(f"[{_now()}]   [{tag}+] {dump}", flush=True)
    return new_off


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extremely detailed monitor for detached RSI-EAF factory"
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=float(os.getenv("MONITOR_INTERVAL_SEC", "8")),
    )
    parser.add_argument(
        "--detail",
        choices=["minimal", "actions", "full", "extreme"],
        default=os.getenv("MONITOR_DETAIL", "extreme"),
    )
    parser.add_argument(
        "--history",
        type=int,
        default=int(os.getenv("MONITOR_FOLLOW_LINES", "100")),
    )
    parser.add_argument(
        "--jsonl",
        action="store_true",
        default=os.getenv("MONITOR_JSONL", "true").lower() in {"1", "true", "yes"},
    )
    parser.add_argument(
        "--all-lines",
        action="store_true",
        default=os.getenv("MONITOR_ALL_LOG_LINES", "true").lower() in {"1", "true", "yes"},
    )
    parser.add_argument("--once", action="store_true")
    parser.add_argument(
        "--no-hybrid",
        action="store_true",
        help="Do not tail hybrid stdout (still tails supervisor)",
    )
    parser.add_argument(
        "--no-x",
        action="store_true",
        help="Do not tail x_daemon stdout",
    )
    args = parser.parse_args()
    detail: str = args.detail
    # extreme implies all log lines
    all_lines = args.all_lines or detail == "extreme"

    os.chdir(ROOT)
    print_banner("RSI-EAF DETAILED FACTORY MONITOR")
    print(f"[{_now()}] root={ROOT}", flush=True)
    print(
        f"[{_now()}] detail={detail} jsonl={args.jsonl} all_lines={all_lines} "
        f"interval={args.interval}s",
        flush=True,
    )
    print(
        f"[{_now()}] logs: supervisor | tee | hybrid | x_daemon | "
        f"{len(JSONL_STREAMS)} jsonl streams",
        flush=True,
    )

    snap = snapshot(detail)
    print_snapshot(snap, detail)

    # History dump — hybrid last N lines (actions), extreme = more
    hist_n = args.history if detail != "extreme" else max(args.history, 120)
    print_banner(f"RECENT SUPERVISOR LOG (last ~{min(hist_n, 40)})")
    for line in _tail_text(SUP_LOG, min(hist_n, 40)):
        if should_emit_log_line(line, detail, all_lines):
            emit_log("sup", line)

    if not args.no_hybrid:
        print_banner(f"RECENT HYBRID ACTIONS (last ~{hist_n})")
        for line in _tail_text(HYBRID_LOG, hist_n):
            if should_emit_log_line(line, detail, all_lines):
                emit_log("hyb", line)

    if not args.no_x:
        print_banner("RECENT X DAEMON")
        for line in _tail_text(X_LOG, 40):
            if should_emit_log_line(line, detail, all_lines):
                emit_log("x", line)

    if args.jsonl and detail in {"full", "extreme"}:
        print_banner("RECENT JSONL ACTION EVENTS")
        for tag, path in JSONL_STREAMS:
            for obj in _tail_jsonl(path, 2 if detail == "full" else 3):
                print(f"[{_now()}] {_fmt_json_event(tag, obj, detail)}", flush=True)

    if args.once:
        return 0 if snap["overall"] != "DOWN" else 1

    # Live offsets — start at EOF so we only show new, after history dump
    off: Dict[str, int] = {
        "sup": _file_offset(SUP_LOG),
        "tee": _file_offset(TEE_LOG),
        "hyb": _file_offset(HYBRID_LOG),
        "x": _file_offset(X_LOG),
    }
    jsonl_off: Dict[str, int] = {tag: _file_offset(path) for tag, path in JSONL_STREAMS}
    last_snap = 0.0
    last_deep = 0.0

    print_banner("LIVE STREAM (factory actions)")
    try:
        while True:
            # Text logs
            streams: List[Tuple[str, Path, str]] = [
                ("sup", SUP_LOG, "sup"),
                ("tee", TEE_LOG, "tee"),
            ]
            if not args.no_hybrid:
                streams.append(("hyb", HYBRID_LOG, "hyb"))
            if not args.no_x:
                streams.append(("x", X_LOG, "x"))

            for key, path, tag in streams:
                chunk, new_off = _read_new(path, off[key])
                off[key] = new_off
                for line in chunk.splitlines():
                    if should_emit_log_line(line, detail, all_lines):
                        emit_log(tag, line)

            # JSONL action events
            if args.jsonl:
                for tag, path in JSONL_STREAMS:
                    jsonl_off[tag] = emit_jsonl_new(tag, path, jsonl_off[tag], detail)

            now = time.time()
            # Frequent short status
            if now - last_snap >= max(4.0, args.interval):
                print_snapshot(snapshot(detail), detail if detail != "extreme" else "full")
                last_snap = now

            # Deep panel less often
            if detail == "extreme" and now - last_deep >= max(30.0, args.interval * 4):
                print_banner("DEEP PANEL")
                print_snapshot(snapshot("extreme"), "extreme")
                # Latest cycle trace phase summary
                traces = _tail_jsonl(OBS / "cycle_traces.jsonl", 8)
                if traces:
                    print(f"[{_now()}] last cycle_traces events:", flush=True)
                    for t in traces:
                        print(
                            f"[{_now()}]   {_fmt_json_event('cycle', t, detail)}",
                            flush=True,
                        )
                last_deep = now

            time.sleep(0.4 if detail == "extreme" else 1.0)
    except KeyboardInterrupt:
        print(f"[{_now()}] monitor stopped", flush=True)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
