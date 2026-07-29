"""
Blocker Guardian — continuous detection, head-on remediation, relentless documentation.

Principles (non-negotiable):
  - Never hide, skip, or reframe a blocker as success.
  - Ops-green is NOT business-green.
  - Every scan writes evidence. Every remediation is logged open or failed.
  - Unresolved blockers stay OPEN until evidence clears them.

Surfaces:
  observability/blocker_status.json     — current open/resolved board
  observability/blocker_guardian.jsonl  — append-only event log
  observability/BLOCKER_RUNBOOK.md      — human-readable living runbook
  published/blockers.json               — public honesty surface
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
OBS = Path(os.getenv("OBSERVABILITY_DIR", "observability"))
PUB = Path(os.getenv("PUBLISHED_DIR", "published"))
RUNTIME = Path("runtime")

STATUS_FILE = OBS / "blocker_status.json"
LOG_FILE = OBS / "blocker_guardian.jsonl"
RUNBOOK_FILE = OBS / "BLOCKER_RUNBOOK.md"
PUB_FILE = PUB / "blockers.json"
HYBRID_LOG = RUNTIME / "factory_runner_stdout.log"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


_RELAUNCH_COOLDOWN_SEC = 300  # 5 min — prevent thrash from repeated guardian passes
_RELAUNCH_STAMP = RUNTIME / "last_detached_relaunch.json"


def _detached_relaunch_allowed() -> Tuple[bool, str]:
    """Rate-limit full stack relaunch so guardian cannot kill a healthy factory."""
    if not _RELAUNCH_STAMP.exists():
        return True, "no_prior"
    try:
        prev = json.loads(_RELAUNCH_STAMP.read_text(encoding="utf-8"))
        age = _age_min(prev.get("at"))
        if age is not None and age * 60 < _RELAUNCH_COOLDOWN_SEC:
            return False, f"cooldown_{age}m_remaining"
    except Exception:
        pass
    return True, "ok"


def _record_detached_relaunch(detail: Dict[str, Any]) -> None:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    _RELAUNCH_STAMP.write_text(
        json.dumps({"at": _now(), **detail}, indent=2, default=str),
        encoding="utf-8",
    )


def _try_detached_relaunch(*, reason: str) -> Dict[str, Any]:
    allowed, why = _detached_relaunch_allowed()
    if not allowed:
        return {"success": False, "skipped": True, "reason": why, "requested_for": reason}
    launch = Path("scripts/launch_factory_detached.py")
    if not launch.exists():
        return {"success": False, "error": "no_launch_script"}
    try:
        r = subprocess.run(
            [sys.executable, "-u", str(launch)],
            cwd=str(Path(".").resolve()),
            timeout=60,
            capture_output=True,
            text=True,
        )
        out = {
            "success": r.returncode == 0,
            "returncode": r.returncode,
            "stdout": (r.stdout or "")[-400:],
            "stderr": (r.stderr or "")[-200:],
            "reason": reason,
        }
        _record_detached_relaunch(out)
        return out
    except Exception as exc:
        return {"success": False, "error": str(exc)[:300], "reason": reason}


def _age_min(iso: Optional[str]) -> Optional[float]:
    if not iso:
        return None
    try:
        t = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return round((datetime.now(timezone.utc) - t).total_seconds() / 60.0, 1)
    except Exception:
        return None


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _append_log(rec: Dict[str, Any]) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, default=str) + "\n")


def _blocker(
    blocker_id: str,
    *,
    severity: str,
    title: str,
    evidence: Dict[str, Any],
    impact: str,
    remediation: str,
    auto_fixable: bool = False,
) -> Dict[str, Any]:
    return {
        "id": blocker_id,
        "severity": severity,  # P0 | P1 | P2 | P3
        "title": title,
        "status": "OPEN",
        "evidence": evidence,
        "impact": impact,
        "remediation": remediation,
        "auto_fixable": auto_fixable,
        "detected_at": _now(),
        "honesty": "not_hidden",
    }


# ---------- detectors ----------


def detect_conversion_down() -> Optional[Dict[str, Any]]:
    try:
        from tools.conversion_surfaces import verify_live

        live = verify_live()
    except Exception as exc:
        return _blocker(
            "conversion_verify_error",
            severity="P0",
            title="Conversion surface verify crashed",
            evidence={"error": str(exc)[:300]},
            impact="Cannot trust pay path; CTAs may be lies",
            remediation="Fix conversion_surfaces.verify_live; force ensure_conversion_surfaces",
            auto_fixable=True,
        )
    # P0 only when pay path is dead (pay.html / agent-pay). Doctrine extras are P2.
    if live.get("pay_ok"):
        if live.get("all_ok"):
            return None
        failed = {
            k: v
            for k, v in (live.get("checks") or {}).items()
            if not (isinstance(v, dict) and v.get("ok"))
        }
        return _blocker(
            "conversion_doctrine_partial",
            severity="P2",
            title="Pay path live; doctrine surfaces incomplete (social/x402)",
            evidence={
                "failed": failed,
                "pay_ok": True,
                "base": live.get("base"),
                "note": "Auto-remediate will regenerate + force Vercel deploy",
            },
            impact="Core CTA works; secondary policy/x402 URLs may 404",
            remediation="tools.factory_remediate.remediate_conversion_and_links(force deploy)",
            auto_fixable=True,
        )
    failed = {
        k: v
        for k, v in (live.get("checks") or {}).items()
        if not (isinstance(v, dict) and v.get("ok"))
    }
    return _blocker(
        "conversion_surfaces_down",
        severity="P0",
        title="Critical pay conversion surfaces not HTTP 200",
        evidence={"failed": failed, "pay_ok": False, "base": live.get("base")},
        impact="Factory markets pay URLs that do not load — zero conversion possible",
        remediation="tools.conversion_surfaces.ensure_conversion_surfaces(force_deploy=True)",
        auto_fixable=True,
    )


def detect_business_red() -> Optional[Dict[str, Any]]:
    try:
        from observability.economic_ledger import ledger

        net = ledger.calculate_net()
    except Exception as exc:
        return _blocker(
            "ledger_unreadable",
            severity="P0",
            title="Economic ledger unreadable",
            evidence={"error": str(exc)[:300]},
            impact="No ground truth on revenue/costs",
            remediation="Repair economic_ledger path and re-ingest treasury",
            auto_fixable=False,
        )
    organic = float(net.get("organic_revenue_usd_est") or 0)
    net_usd = float(net.get("net_usd_est") or 0)
    costs = float(net.get("total_cost_usd_est") or 0)
    if organic <= 0 or net_usd < 0:
        return _blocker(
            "business_red",
            severity="P0",
            title="Business-red: organic revenue insufficient / lifetime net negative",
            evidence={
                "organic_revenue_usd_est": organic,
                "net_usd_est": net_usd,
                "total_cost_usd_est": costs,
                "total_revenue_usd_est": net.get("total_revenue_usd_est"),
            },
            impact="Primary AGENTS.md goal unmet — ops-green is irrelevant until external organic payers move the ledger",
            remediation=(
                "tools.factory_remediate.remediate_business_red: max capture machinery "
                "(surfaces+outreach+ingest+sprint). Stays OPEN until external organic ledger rises."
            ),
            # Capture machinery is auto-run; revenue clearing is never auto-claimed
            auto_fixable=True,
        )
    return None


def detect_hybrid_down(hybrid_pid: Optional[int] = None) -> Optional[Dict[str, Any]]:
    if hybrid_pid:
        return None
    return _blocker(
        "hybrid_process_down",
        severity="P0",
        title="Hybrid continuous runner process not alive",
        evidence={"hybrid_pid": hybrid_pid},
        impact="No economic cycles advancing",
        remediation="Supervisor must respawn scripts/run_continuous_hybrid.py",
        auto_fixable=True,
    )


def detect_x_daemon_down(x_pid: Optional[int] = None) -> Optional[Dict[str, Any]]:
    if x_pid:
        return None
    return _blocker(
        "x_daemon_down",
        severity="P1",
        title="X operator daemon not alive",
        evidence={"x_daemon_pid": x_pid},
        impact="No continuous social watch/engage/learning ticks",
        remediation="Supervisor must respawn observability/x_daemon.py",
        auto_fixable=True,
    )


def detect_hybrid_stuck_in_boot(hybrid_pid: Optional[int] = None, uptime_min: float = 0.0) -> Optional[Dict[str, Any]]:
    if not hybrid_pid or uptime_min < 8:
        return None
    if not HYBRID_LOG.exists():
        return _blocker(
            "hybrid_log_missing",
            severity="P1",
            title="Hybrid log missing while process claims UP",
            evidence={"hybrid_pid": hybrid_pid, "log": str(HYBRID_LOG)},
            impact="Cannot verify cycle progress — observability hole",
            remediation="Ensure supervisor pumps hybrid stdout to factory_runner_stdout.log",
            auto_fixable=False,
        )
    try:
        tail = HYBRID_LOG.read_text(encoding="utf-8", errors="replace")[-12000:]
    except OSError as exc:
        return _blocker(
            "hybrid_log_unreadable",
            severity="P1",
            title="Hybrid log unreadable",
            evidence={"error": str(exc)[:200]},
            impact="Blind to cycle progress",
            remediation="Fix log permissions/path",
            auto_fixable=False,
        )
    has_cycle = any(m in tail for m in ("[Director]", "[Cycle]", "Starting Cycle", "Phase 1:"))
    has_deadlock_symptom = (
        "[TreasuryDaemon] Listening" in tail
        and "[AutonomousRunner] Daemon" not in tail
        and uptime_min > 10
    )
    if has_deadlock_symptom:
        return _blocker(
            "hybrid_daemon_register_deadlock",
            severity="P0",
            title="Hybrid boot appears stuck after treasury (classic register_daemon deadlock pattern)",
            evidence={"uptime_min": uptime_min, "tail_snippet": tail[-400:]},
            impact="No cycles forever; process looks UP",
            remediation="Ensure daemon_supervisor.register_daemon starts outside _lock; restart hybrid",
            auto_fixable=True,
        )
    if uptime_min >= 15 and not has_cycle:
        return _blocker(
            "hybrid_no_cycle_progress",
            severity="P1",
            title="Hybrid up but no cycle log markers after substantial uptime",
            evidence={"uptime_min": uptime_min, "markers_found": False},
            impact="Economic loop stalled; scoreboard freezes",
            remediation="Restart hybrid; enforce FACTORY_SKIP_TOOL_PHASE; check daily review hang",
            auto_fixable=True,
        )
    return None


def detect_stale_x_tick() -> Optional[Dict[str, Any]]:
    st = _read_json(OBS / "x_agent_state.json")
    age = _age_min(st.get("last_tick_at"))
    if age is None:
        return _blocker(
            "x_tick_never",
            severity="P1",
            title="X agent has never recorded a tick",
            evidence={"state": "missing last_tick_at"},
            impact="Social operator not producing evidence",
            remediation="Restart x_daemon; verify OAuth ready",
            auto_fixable=True,
        )
    if age > 15:
        return _blocker(
            "x_tick_stale",
            severity="P1",
            title=f"X agent tick stale ({age} min)",
            evidence={"last_tick_at": st.get("last_tick_at"), "age_min": age},
            impact="Mentions/pay intent may go unanswered",
            remediation="Restart x_daemon; check API credits/errors in x_agent.jsonl",
            auto_fixable=True,
        )
    return None


def detect_runner_lock_stale() -> Optional[Dict[str, Any]]:
    lock = Path("factory_core/.runner.lock")
    if not lock.exists():
        return None
    try:
        pid = int(lock.read_text(encoding="utf-8").strip().splitlines()[0])
    except (OSError, ValueError):
        return _blocker(
            "runner_lock_corrupt",
            severity="P1",
            title="Runner lock file corrupt",
            evidence={"path": str(lock)},
            impact="Hybrid may refuse to start",
            remediation="Delete factory_core/.runner.lock",
            auto_fixable=True,
        )
    # alive check
    alive = False
    if os.name == "nt":
        try:
            r = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            alive = str(pid) in (r.stdout or "") and "No tasks" not in (r.stdout or "")
        except Exception:
            alive = False
    else:
        try:
            os.kill(pid, 0)
            alive = True
        except OSError:
            alive = False
    if not alive:
        return _blocker(
            "runner_lock_stale",
            severity="P1",
            title=f"Stale runner lock held by dead PID {pid}",
            evidence={"pid": pid},
            impact="Blocks hybrid restart",
            remediation="Unlink factory_core/.runner.lock",
            auto_fixable=True,
        )
    return None


def detect_pay_cta_vs_live_mismatch() -> Optional[Dict[str, Any]]:
    """If recent social posts mention pay.html but live is down — honesty violation."""
    try:
        from tools.link_watcher import assert_cta_links_ok

        gate = assert_cta_links_ok(force_refresh=False)
        if gate.get("ok"):
            return None
        return _blocker(
            "cta_to_dead_pay",
            severity="P0",
            title="Pay CTA links are DOWN (link watcher)",
            evidence={
                "pay_url": gate.get("pay_url"),
                "agent_pay_url": gate.get("agent_pay_url"),
                "pay_probe": gate.get("pay_probe"),
                "agent_probe": gate.get("agent_probe"),
                "block_reason": gate.get("block_reason"),
            },
            impact="Active dishonesty to audience — worst-mode conversion failure",
            remediation="run tools.link_watcher.run_link_watcher(remediate=True); halt pay posts",
            auto_fixable=True,
        )
    except Exception:
        pass
    try:
        from tools.conversion_surfaces import verify_live

        live = verify_live()
        pay_ok = live.get("pay_ok") or (live.get("checks") or {}).get("/pay.html", {}).get("ok")
    except Exception:
        return None
    if pay_ok:
        return None
    st = _read_json(OBS / "x_agent_state.json")
    recent = list(st.get("recent_post_texts") or [])[-5:]
    if any("pay.html" in (t or "") for t in recent):
        return _blocker(
            "cta_to_dead_pay",
            severity="P0",
            title="Recent posts CTA to pay.html while pay surface is DOWN",
            evidence={"recent_posts_with_pay": True, "pay_ok": pay_ok},
            impact="Active dishonesty to audience — worst-mode conversion failure",
            remediation="Immediate ensure_conversion_surfaces; halt pay-link posts until 200",
            auto_fixable=True,
        )
    return None


def detect_link_watcher_failures() -> Optional[Dict[str, Any]]:
    """P0 if critical advertised links fail health checks."""
    try:
        from tools.link_watcher import run_link_watcher

        report = run_link_watcher(remediate=False)
        summary = report.get("summary") or (report.get("probe") or {}).get("summary") or {}
        if summary.get("safe_to_post") and summary.get("critical_failed", 0) == 0:
            return None
        return _blocker(
            "social_links_down",
            severity="P0" if not summary.get("safe_to_post") else "P1",
            title="Factory social/public links failing health checks",
            evidence={
                "summary": summary,
                "failed_urls": (report.get("probe") or report).get("failed_urls")
                or report.get("failed_urls"),
                "critical_failed_urls": (report.get("probe") or report).get("critical_failed_urls")
                or report.get("critical_failed_urls"),
                "preferred_cta": report.get("preferred_cta"),
            },
            impact="Social posts point at 404s — zero conversion, reputation damage",
            remediation="tools.link_watcher.run_link_watcher(remediate=True); force CDN CTA",
            auto_fixable=True,
        )
    except Exception as exc:
        return _blocker(
            "link_watcher_error",
            severity="P1",
            title="Link watcher failed to run",
            evidence={"error": str(exc)[:300]},
            impact="Blind spot on public URL integrity",
            remediation="Fix tools/link_watcher.py",
            auto_fixable=False,
        )


def detect_register_daemon_deadlock_code() -> Optional[Dict[str, Any]]:
    """Static guard: register_daemon must not call start_fn under lock."""
    path = Path("observability/daemon_supervisor.py")
    if not path.exists():
        return None
    try:
        src = path.read_text(encoding="utf-8")
    except OSError:
        return None
    # crude but effective: look for fixed pattern documentation
    if "start_fn must run *outside* _lock" in src or "Start outside lock" in src:
        return None
    # regression: start_fn inside with _lock block before our fix
    if re.search(r"with _lock:[\s\S]{0,200}result = start_fn\(\)", src):
        return _blocker(
            "code_regression_register_daemon_deadlock",
            severity="P0",
            title="Code regression: register_daemon may deadlock (start_fn under lock)",
            evidence={"file": str(path)},
            impact="Hybrid will hang after treasury forever",
            remediation="Restore start_fn outside lock in register_daemon",
            auto_fixable=False,
        )
    return None


# ---------- remediation ----------


def remediate(blocker: Dict[str, Any], *, hybrid_restart: Optional[Callable[[], None]] = None) -> Dict[str, Any]:
    bid = blocker.get("id")
    action = {"blocker_id": bid, "at": _now(), "attempted": True, "success": False}

    try:
        if bid in {
            "conversion_surfaces_down",
            "conversion_doctrine_partial",
            "conversion_verify_error",
            "cta_to_dead_pay",
            "social_links_down",
        }:
            # Aggressive fix path: regenerate all local surfaces → force deploy → re-verify
            from tools.factory_remediate import remediate_conversion_and_links

            r = remediate_conversion_and_links()
            verify = r.get("verify") or {}
            checks = verify.get("checks") or {}
            pay_ok = bool((checks.get("pay.html") or {}).get("ok"))
            doctrine_ok = all(
                (checks.get(k) or {}).get("ok")
                for k in ("icp.json", "social-policy.json", "social-learning.json")
            )
            action["result"] = {
                "engine": "factory_remediate.remediate_conversion_and_links",
                "success": r.get("success"),
                "pay_ok": pay_ok,
                "doctrine_ok": doctrine_ok,
                "all_ok": verify.get("all_ok"),
                "failed": {
                    k: v
                    for k, v in checks.items()
                    if not (isinstance(v, dict) and v.get("ok"))
                },
                "link_watcher": r.get("link_watcher"),
                "steps": [
                    {"step": s.get("step"), "ok": s.get("ok")}
                    for s in (r.get("steps") or [])
                ],
            }
            if bid == "conversion_doctrine_partial":
                action["success"] = bool(doctrine_ok and pay_ok)
            elif bid in {"conversion_surfaces_down", "cta_to_dead_pay", "conversion_verify_error"}:
                action["success"] = bool(pay_ok)
            else:  # social_links_down
                lw = r.get("link_watcher") or {}
                action["success"] = bool(
                    pay_ok or lw.get("safe_to_post") or lw.get("pay_surface_ok")
                )

        elif bid in {"runner_lock_stale", "runner_lock_corrupt"}:
            lock = Path("factory_core/.runner.lock")
            lock.unlink(missing_ok=True)
            action["success"] = not lock.exists()
            action["result"] = {"lock_removed": action["success"]}

        elif bid in {
            "hybrid_process_down",
            "hybrid_no_cycle_progress",
            "hybrid_daemon_register_deadlock",
        }:
            if hybrid_restart:
                hybrid_restart()
                action["success"] = True
                action["result"] = {"hybrid_restart_invoked": True}
            else:
                # No supervisor callback — rate-limited detached relaunch
                out = _try_detached_relaunch(reason=str(bid))
                action["success"] = bool(out.get("success"))
                action["result"] = out

        elif bid == "x_daemon_down":
            # Process gone — rate-limited full stack relaunch if no supervisor callback
            out = _try_detached_relaunch(reason="x_daemon_down")
            action["success"] = bool(out.get("success"))
            action["result"] = out
            if not out.get("success"):
                action["needs_supervisor_respawn"] = "x_daemon"

        elif bid in {"x_tick_stale", "x_tick_never"}:
            # Process may be up but idle — do not thrash full relaunch; force one x tick if possible
            try:
                from observability import x_daemon as xd

                tick_fn = getattr(xd, "run_once", None) or getattr(xd, "tick", None)
                if tick_fn:
                    tick_fn()
                    action["success"] = True
                    action["result"] = {"forced_x_tick": True}
                else:
                    action["result"] = {
                        "note": "x daemon alive but tick stale; waiting for next interval"
                    }
                    action["success"] = False
            except Exception as exc:
                action["result"] = {"error": str(exc)[:200]}
                action["success"] = False

        elif bid == "business_red":
            # Cannot invent payers, but MUST max capture machinery (surfaces+outreach+ingest)
            from tools.factory_remediate import remediate_business_red

            r = remediate_business_red()
            action["result"] = {
                "engine": "factory_remediate.remediate_business_red",
                "machinery_ok": r.get("success"),
                "note": r.get("note"),
                "steps": [
                    {"step": s.get("step"), "ok": s.get("ok")}
                    for s in (r.get("steps") or [])
                ],
                "honest": True,
                "message": (
                    "Capture machinery maximized; business_red stays OPEN until "
                    "external organic ledger revenue rises."
                ),
            }
            # Never auto-clear: revenue truth only. success=False keeps OPEN honestly.
            action["success"] = False
            action["machinery_remediated"] = bool(r.get("success"))

        else:
            action["result"] = {"error": f"no_auto_remediation_for:{bid}"}

    except Exception as exc:
        action["success"] = False
        action["result"] = {"error": str(exc)[:400]}

    action["status_after"] = "REMEDIATED" if action["success"] else "OPEN"
    return action


# ---------- scan + document ----------


def scan_blockers(
    *,
    hybrid_pid: Optional[int] = None,
    x_daemon_pid: Optional[int] = None,
    hybrid_uptime_min: float = 0.0,
) -> List[Dict[str, Any]]:
    detectors = [
        detect_conversion_down,
        detect_link_watcher_failures,
        detect_business_red,
        detect_pay_cta_vs_live_mismatch,
        detect_register_daemon_deadlock_code,
        lambda: detect_hybrid_down(hybrid_pid),
        lambda: detect_x_daemon_down(x_daemon_pid),
        lambda: detect_hybrid_stuck_in_boot(hybrid_pid, hybrid_uptime_min),
        detect_stale_x_tick,
        detect_runner_lock_stale,
    ]
    found: List[Dict[str, Any]] = []
    for det in detectors:
        try:
            b = det()
            if b:
                found.append(b)
        except Exception as exc:
            found.append(
                _blocker(
                    f"detector_crash_{getattr(det, '__name__', 'anon')}",
                    severity="P1",
                    title="Blocker detector crashed",
                    evidence={"error": str(exc)[:300]},
                    impact="Blind spot in guardian",
                    remediation="Fix detector exception",
                    auto_fixable=False,
                )
            )
    # severity sort
    order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    found.sort(key=lambda x: order.get(str(x.get("severity")), 9))
    return found


def write_runbook(open_blockers: List[Dict[str, Any]], remediations: List[Dict[str, Any]]) -> None:
    lines = [
        "# Blocker Runbook — living document",
        "",
        f"**Updated:** {_now()}",
        "",
        "This file is rewritten every guardian scan. **OPEN blockers are never omitted.**",
        "",
        "## Principles",
        "",
        "1. Do not hide blockers behind ops-green language.",
        "2. Business-red stays OPEN until the ledger moves with external organic revenue.",
        "3. Every auto-remediation is logged success or failure.",
        "4. If you cannot fix it in code, document the human/external dependency explicitly.",
        "",
        f"## OPEN blockers ({len(open_blockers)})",
        "",
    ]
    if not open_blockers:
        lines.append("_No automated detectors fired. This does not mean product-market fit._")
        lines.append("")
    for b in open_blockers:
        lines += [
            f"### [{b.get('severity')}] `{b.get('id')}` — {b.get('title')}",
            "",
            f"- **Impact:** {b.get('impact')}",
            f"- **Remediation:** {b.get('remediation')}",
            f"- **Auto-fixable:** {b.get('auto_fixable')}",
            f"- **Detected:** {b.get('detected_at')}",
            f"- **Evidence:** `{json.dumps(b.get('evidence'), default=str)[:500]}`",
            "",
        ]
    lines += ["## Last remediations this scan", ""]
    if not remediations:
        lines.append("_None attempted._")
        lines.append("")
    for r in remediations:
        lines += [
            f"- `{r.get('blocker_id')}` → success={r.get('success')} status={r.get('status_after')} "
            f"result={json.dumps(r.get('result'), default=str)[:200]}",
        ]
    lines += [
        "",
        "## How to inspect anytime",
        "",
        "```",
        "type observability\\blocker_status.json",
        "type observability\\BLOCKER_RUNBOOK.md",
        "Get-Content observability\\blocker_guardian.jsonl -Tail 20",
        "```",
        "",
    ]
    RUNBOOK_FILE.parent.mkdir(parents=True, exist_ok=True)
    RUNBOOK_FILE.write_text("\n".join(lines), encoding="utf-8")


# Heavy remediations (deploy/outreach) must not run every supervisor heartbeat
_HEAVY_REMEDIATE_COOLDOWN_MIN = {
    "business_red": 45.0,
    "conversion_doctrine_partial": 20.0,
    "conversion_surfaces_down": 10.0,
    "social_links_down": 15.0,
    "conversion_verify_error": 10.0,
    "cta_to_dead_pay": 10.0,
}
_REMEDIATE_STAMP = OBS / "blocker_remediate_cooldowns.json"


def _remediation_on_cooldown(bid: str) -> Tuple[bool, str]:
    """Return (on_cooldown, reason). Cheap blockers (locks, process) never cool down."""
    cool = _HEAVY_REMEDIATE_COOLDOWN_MIN.get(str(bid or ""))
    if cool is None:
        return False, "no_cooldown"
    try:
        data = json.loads(_REMEDIATE_STAMP.read_text(encoding="utf-8")) if _REMEDIATE_STAMP.exists() else {}
        last = (data.get(bid) or {}).get("at")
        age = _age_min(last)
        if age is not None and age < cool:
            return True, f"cooldown_{age:.0f}/{cool:.0f}m"
    except Exception:
        pass
    return False, "ok"


def _mark_remediation_attempted(bid: str, rem: Dict[str, Any]) -> None:
    if str(bid) not in _HEAVY_REMEDIATE_COOLDOWN_MIN:
        return
    try:
        data = {}
        if _REMEDIATE_STAMP.exists():
            data = json.loads(_REMEDIATE_STAMP.read_text(encoding="utf-8"))
        data[str(bid)] = {
            "at": _now(),
            "success": rem.get("success"),
            "machinery_remediated": rem.get("machinery_remediated"),
        }
        OBS.mkdir(parents=True, exist_ok=True)
        _REMEDIATE_STAMP.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass


def run_guardian_pass(
    *,
    hybrid_pid: Optional[int] = None,
    x_daemon_pid: Optional[int] = None,
    hybrid_uptime_min: float = 0.0,
    hybrid_restart: Optional[Callable[[], None]] = None,
    x_restart: Optional[Callable[[], None]] = None,
) -> Dict[str, Any]:
    """
    Full scan → remediate auto-fixable → document relentlessly.
    Returns status payload for scoreboard/supervisor.

    Heavy remediations (business_red capture, conversion deploys) are rate-limited
    so the supervisor heartbeat cannot hang for 15+ minutes every cycle.
    """
    found = scan_blockers(
        hybrid_pid=hybrid_pid,
        x_daemon_pid=x_daemon_pid,
        hybrid_uptime_min=hybrid_uptime_min,
    )
    remediations: List[Dict[str, Any]] = []
    still_open: List[Dict[str, Any]] = []

    for b in found:
        _append_log({"event": "detected", "blocker": b})
        # Always attempt remediation for auto_fixable blockers AND business_red
        # (business_red runs capture machinery but never auto-clears).
        should_fix = bool(b.get("auto_fixable")) or b.get("id") == "business_red"
        if should_fix:
            bid = str(b.get("id") or "")
            on_cd, cd_why = _remediation_on_cooldown(bid)
            if on_cd:
                rem = {
                    "blocker_id": bid,
                    "at": _now(),
                    "attempted": False,
                    "success": False,
                    "status_after": "OPEN",
                    "result": {"skipped": True, "reason": cd_why},
                    "machinery_remediated": bid == "business_red",
                }
                remediations.append(rem)
                still_open.append({**b, "status": "OPEN", "last_remediation": rem})
                continue
            if b.get("id") in {"x_daemon_down", "x_tick_stale", "x_tick_never"} and x_restart:
                try:
                    x_restart()
                    rem = {
                        "blocker_id": b.get("id"),
                        "at": _now(),
                        "attempted": True,
                        "success": True,
                        "status_after": "REMEDIATED",
                        "result": {"x_restart_invoked": True},
                    }
                except Exception as exc:
                    rem = {
                        "blocker_id": b.get("id"),
                        "at": _now(),
                        "attempted": True,
                        "success": False,
                        "status_after": "OPEN",
                        "result": {"error": str(exc)[:200]},
                    }
            else:
                rem = remediate(b, hybrid_restart=hybrid_restart)
            _mark_remediation_attempted(bid, rem)
            remediations.append(rem)
            _append_log({"event": "remediation", **rem})
            if rem.get("success"):
                b = {**b, "status": "REMEDIATED", "remediated_at": _now(), "remediation_result": rem}
            else:
                # business_red / partial failures stay OPEN with evidence of attempted fix
                b = {
                    **b,
                    "status": "OPEN",
                    "last_remediation": rem,
                    "machinery_remediated": rem.get("machinery_remediated"),
                }
                still_open.append(b)
        else:
            still_open.append(b)

    # Re-scan conversion after remediation
    residual = []
    for b in still_open:
        # keep business_red always if still red
        residual.append(b)

    # refresh conversion after remediations
    conv = detect_conversion_down()
    if conv and not any(x.get("id") == conv["id"] for x in residual):
        residual.append(conv)
    biz = detect_business_red()
    if biz and not any(x.get("id") == "business_red" for x in residual):
        residual.append(biz)

    order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    residual.sort(key=lambda x: order.get(str(x.get("severity")), 9))

    payload = {
        "schema": "rsi_eaf_blocker_status_v1",
        "updated_at": _now(),
        "honesty": "open_blockers_never_hidden",
        "open_count": len(residual),
        "p0_count": sum(1 for b in residual if b.get("severity") == "P0"),
        "open_blockers": residual,
        "remediations_this_pass": remediations,
        "detected_this_pass": [b.get("id") for b in found],
        "ops_note": (
            "If open_count==0 for ops detectors, business_red may still be OPEN. "
            "Never report factory 'healthy' while business_red is OPEN."
        ),
    }

    OBS.mkdir(parents=True, exist_ok=True)
    PUB.mkdir(parents=True, exist_ok=True)
    STATUS_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    PUB_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    write_runbook(residual, remediations)
    _append_log({"event": "scan_complete", "open_count": len(residual), "ids": [b.get("id") for b in residual]})

    return payload


if __name__ == "__main__":
    try:
        from dotenv import load_dotenv

        load_dotenv(override=True)
    except Exception:
        pass
    out = run_guardian_pass()
    print(json.dumps({"open_count": out.get("open_count"), "ids": [b.get("id") for b in out.get("open_blockers") or []]}, indent=2))
    for b in out.get("open_blockers") or []:
        print(f"  [{b.get('severity')}] {b.get('id')}: {b.get('title')}")
