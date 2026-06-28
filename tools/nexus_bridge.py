"""
RSI-EAF ↔ aetherforge.world bridge.

Emits factory cycle observability to theCeramist/jarvis-swarm (nexus_data.json merge)
so aetherforge.world refreshes via Vercel. Pattern from emit_nexus_wave.py +
grok-agents-orchestrator WebSocket/nexus dashboard observability.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from observability.economic_ledger import ledger
from tools.github_distribution import distribution_urls
from tools.publish_tools import deploy_cooldown_status, verify_live_url

NEXUS_OWNER = os.getenv("NEXUS_GITHUB_OWNER", "theCeramist")
NEXUS_REPO = os.getenv("NEXUS_GITHUB_REPO", "jarvis-swarm")
NEXUS_BRANCH = os.getenv("NEXUS_GITHUB_BRANCH", "main")
def _nexus_emit_enabled() -> bool:
    return os.getenv("NEXUS_EMIT_ENABLED", "true").lower() in {"1", "true", "yes"}


def _nexus_emit_every_n() -> int:
    return int(os.getenv("NEXUS_EMIT_EVERY_N_CYCLES", "1"))
AETHERFORGE_URL = os.getenv("AETHERFORGE_URL", "https://aetherforge.world").rstrip("/")
FACTORY_PUBLIC_BASE_URL = os.getenv("FACTORY_PUBLIC_BASE_URL", "https://published-zeta.vercel.app").rstrip("/")
LOCAL_NEXUS_DIR = Path(os.getenv("NEXUS_LOCAL_DIR", "observability/nexus"))
TRACE_FILE = Path(os.getenv("FACTORY_TRACE_FILE", "observability/cycle_traces.jsonl"))
DIRECTOR_LOG = Path(os.getenv("DIRECTOR_DECISIONS_LOG", "factory_core/director_decisions.jsonl"))

THE_FOUR_CONTROL_STATE_GOALS = [
    "Improve coordination, outcome evaluation, and learning between parallel sub-agents",
    "Enhance observability and GitNexus persistence of autonomous subagent runs",
    "Evolve stronger human-swarm symbiosis surface in response to recent Nexus interaction",
    "Strengthen self-sufficiency monitoring, bottleneck detection, and autonomous pause/resume logic",
]

ASI_TIER_1 = (
    "Real intelligence traces + mandatory external Vercel/Nexus feedback on live "
    "aetherforge.world / theCeramist/jarvis-swarm / theCeramist/rsi-eaf. "
    "RSI-EAF factory cycles anchored on XRPL with verifiable revenue surfaces."
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _github_token() -> Optional[str]:
    return os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")


def _github_headers() -> Dict[str, str]:
    token = _github_token()
    if not token:
        return {}
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _fetch_repo_json(path: str) -> Optional[Dict[str, Any]]:
    token = _github_token()
    if not token:
        return None
    url = f"https://api.github.com/repos/{NEXUS_OWNER}/{NEXUS_REPO}/contents/{path}"
    try:
        response = httpx.get(
            url,
            headers=_github_headers(),
            params={"ref": NEXUS_BRANCH},
            timeout=30.0,
        )
        if response.status_code != 200:
            return None
        import base64

        raw = response.json().get("content", "")
        decoded = base64.b64decode(raw).decode("utf-8")
        return json.loads(decoded)
    except (httpx.HTTPError, json.JSONDecodeError, ValueError):
        return None


def _get_file_sha(path: str) -> Optional[str]:
    token = _github_token()
    if not token:
        return None
    url = f"https://api.github.com/repos/{NEXUS_OWNER}/{NEXUS_REPO}/contents/{path}"
    try:
        response = httpx.get(
            url,
            headers=_github_headers(),
            params={"ref": NEXUS_BRANCH},
            timeout=30.0,
        )
        if response.status_code == 200:
            return response.json().get("sha")
    except httpx.HTTPError:
        pass
    return None


def push_nexus_file(path: str, content: str, message: str) -> Dict[str, Any]:
    """Push a single file to jarvis-swarm (aetherforge data source)."""
    import base64

    token = _github_token()
    if not token:
        return {"success": False, "skipped": True, "reason": "no_github_token"}

    payload: Dict[str, Any] = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
        "branch": NEXUS_BRANCH,
    }
    sha = _get_file_sha(path)
    if sha:
        payload["sha"] = sha

    url = f"https://api.github.com/repos/{NEXUS_OWNER}/{NEXUS_REPO}/contents/{path}"
    try:
        response = httpx.put(url, headers=_github_headers(), json=payload, timeout=60.0)
        ok = response.status_code in {200, 201}
        return {
            "success": ok,
            "path": path,
            "status_code": response.status_code,
            "detail": "ok" if ok else response.text[-300:],
        }
    except httpx.HTTPError as exc:
        return {"success": False, "path": path, "error": str(exc)}


def _tail_jsonl(path: Path, limit: int = 20) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    entries = []
    for line in lines[-limit:]:
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def _recent_cycle_traces(cycle_id: int, limit: int = 12) -> List[Dict[str, Any]]:
    traces = _tail_jsonl(TRACE_FILE, limit=200)
    return [t for t in traces if t.get("cycle_id") == cycle_id][-limit:]


def _latest_director_decision(cycle_id: int) -> Optional[Dict[str, Any]]:
    for entry in reversed(_tail_jsonl(DIRECTOR_LOG, limit=50)):
        if entry.get("after_cycle_id") == cycle_id:
            return entry
    return None


def assemble_factory_wave(cycle_result: Dict[str, Any]) -> Dict[str, Any]:
    """Build RSI-EAF factory payload for aetherforge / jarvis-swarm."""
    cycle_id = int(cycle_result.get("cycle_id", 0))
    execution = cycle_result.get("execution", {})
    analysis = cycle_result.get("analysis", {})
    gates = cycle_result.get("gates", {})
    net = cycle_result.get("ledger_net", ledger.calculate_net())
    factory_state = cycle_result.get("factory_state", {})
    github_dist = execution.get("github_distribution", {})
    featured = execution.get("featured_surfaces", {})
    director = _latest_director_decision(cycle_id)

    phase_traces = _recent_cycle_traces(cycle_id)
    dist_urls = distribution_urls(cycle_id)

    gist_url = github_dist.get("gist", {}).get("gist_url") or dist_urls.get("gist_url")
    release_url = github_dist.get("release", {}).get("html_url") or dist_urls.get("github_release")
    outreach_path = Path("published") / f"outreach-cycle-{cycle_id}.json"
    outreach = {}
    if outreach_path.exists():
        try:
            outreach = json.loads(outreach_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    revenue_cta = {
        "headline": "Support RSI-EAF — XRPL Testnet",
        "tip_url": featured.get("canonical_tip_page") or featured.get("tip_page"),
        "briefing_url": featured.get("briefing_page"),
        "gist_url": gist_url,
        "release_url": release_url,
        "github_issue": dist_urls.get("github_issue"),
        "treasury": execution.get("treasury_address"),
        "destination_tag_tip": 1,
        "destination_tag_briefing": 2,
        "outreach_snippet": outreach.get("share_text", "")[:500],
    }

    factory_block = {
        "factory_name": "RSI-EAF",
        "cycle_id": cycle_id,
        "timestamp": _now_iso(),
        "status": "running" if cycle_result.get("success") else "degraded",
        "mode": execution.get("cycle_mode", os.getenv("CYCLE_MODE", "hybrid")),
        "focus": analysis.get("cycle_focus", os.getenv("CYCLE_FOCUS", "revenue")),
        "ledger_net": net,
        "organic_revenue_usd": net.get("organic_revenue_usd_est", 0),
        "xrpl_factory_address": cycle_result.get("xrpl_factory_address"),
        "treasury_address": execution.get("treasury_address"),
        "current_xrp_balance": cycle_result.get("current_xrp_balance"),
        "gates": {
            "all_passed": gates.get("all_passed"),
            "passed": gates.get("passed_count"),
            "total": gates.get("total_count"),
        },
        "revenue_surfaces": featured,
        "github": {
            **dist_urls,
            **({"gist_url": github_dist.get("gist", {}).get("gist_url")} if github_dist.get("gist") else {}),
            "distribution": github_dist,
            "factory_repo": f"https://github.com/{os.getenv('GITHUB_DISTRIBUTION_OWNER', 'theCeramist')}/{os.getenv('GITHUB_DISTRIBUTION_REPO', 'rsi-eaf')}",
        },
        "vercel": {
            "public_base_url": FACTORY_PUBLIC_BASE_URL,
            "live_url": execution.get("live_url"),
            "deploy": execution.get("vercel_deploy"),
            "cooldown": execution.get("vercel_cooldown"),
        },
        "director_decision": director,
        "analysis_summary": {
            "cycle_revenue_usd": analysis.get("cycle_revenue_usd"),
            "bottlenecks": analysis.get("bottlenecks", [])[:5],
            "recommendations": analysis.get("recommendations", [])[:5],
        },
        "evolution": {
            "proposals_count": len(cycle_result.get("proposals", [])),
            "executor": (cycle_result.get("evolution") or {}).get("executor"),
        },
        "phase_traces": phase_traces,
        "control_state_goals": THE_FOUR_CONTROL_STATE_GOALS,
        "asi_tier_1": ASI_TIER_1,
        "factory_state_snapshot": factory_state,
        "revenue_cta": revenue_cta,
    }

    return {
        "wave_id": f"rsi-eaf-cycle-{cycle_id}-{_now_iso()}",
        "timestamp": _now_iso(),
        "rsi_eaf_factory": factory_block,
        "cycle_summary": {
            "cycle_id": cycle_id,
            "net_usd_est": net.get("net_usd_est"),
            "revenue_usd_est": net.get("total_revenue_usd_est"),
            "gates_passed": gates.get("all_passed"),
            "live_verified": execution.get("live_verified"),
        },
        "high_density_observability": {
            "rsi_eaf_factory_cycle": factory_block,
            "per_cycle_breakdowns": {
                "factory_cycles_completed": factory_state.get("cycles_completed", cycle_id),
                "coordination_quality": 0.85 if gates.get("all_passed") else 0.6,
            },
            "tool_usage_traces": [
                {
                    "specialist": phase.get("phase", "unknown"),
                    "duration_ms": phase.get("duration_ms"),
                    "outcome": "ok",
                    "linked_4_control_state_goals": THE_FOUR_CONTROL_STATE_GOALS,
                }
                for phase in phase_traces
            ],
        },
        "revenue_cta": revenue_cta,
        "external_links": {
            "aetherforge": AETHERFORGE_URL,
            "factory_vercel": FACTORY_PUBLIC_BASE_URL,
            "github_rsi_eaf": dist_urls.get("github_repo"),
            "github_jarvis_swarm": f"https://github.com/{NEXUS_OWNER}/{NEXUS_REPO}",
        },
        "version": "rsi-eaf-nexus-v1",
    }


def merge_nexus_data(existing: Optional[Dict[str, Any]], wave: Dict[str, Any]) -> Dict[str, Any]:
    """Merge RSI-EAF factory data into jarvis-swarm nexus_data without clobbering swarm state."""
    merged = dict(existing or {})
    merged["rsi_eaf_factory"] = wave["rsi_eaf_factory"]
    merged["rsi_eaf_wave_id"] = wave["wave_id"]
    merged["rsi_eaf_last_emit"] = wave["timestamp"]

    hd = dict(merged.get("high_density_observability") or {})
    hd["rsi_eaf_factory_cycle"] = wave["high_density_observability"]["rsi_eaf_factory_cycle"]
    hd["rsi_eaf_per_cycle"] = wave["high_density_observability"].get("per_cycle_breakdowns")
    if wave.get("revenue_cta"):
        hd["revenue_cta"] = wave["revenue_cta"]
    if wave["high_density_observability"].get("tool_usage_traces"):
        existing_traces = list(hd.get("tool_usage_traces") or [])
        hd["rsi_eaf_phase_traces"] = wave["high_density_observability"]["tool_usage_traces"]
        hd["tool_usage_traces"] = existing_traces + wave["high_density_observability"]["tool_usage_traces"][-6:]
    merged["high_density_observability"] = hd

    if "control_state_goals" not in merged:
        merged["control_state_goals"] = THE_FOUR_CONTROL_STATE_GOALS
    if "asi_tier_1" not in merged:
        merged["asi_tier_1"] = ASI_TIER_1
    return merged


def merge_control_state(existing: Optional[Dict[str, Any]], wave: Dict[str, Any]) -> Dict[str, Any]:
    """Add RSI-EAF runner heartbeat to control-state.json."""
    factory = wave["rsi_eaf_factory"]
    merged = dict(existing or {})
    merged["rsi_eaf_runner"] = {
        "status": "alive",
        "last_heartbeat": wave["timestamp"],
        "cycle_id": factory["cycle_id"],
        "net_usd_est": factory["ledger_net"].get("net_usd_est"),
        "organic_revenue_usd": factory.get("organic_revenue_usd"),
        "gates_passed": factory["gates"].get("all_passed"),
        "focus": factory.get("focus"),
        "live_url": FACTORY_PUBLIC_BASE_URL,
        "aetherforge_linked": True,
    }
    merged["last_updated"] = wave["timestamp"]
    if "message" not in merged or not merged.get("message"):
        merged["message"] = f"RSI-EAF factory cycle {factory['cycle_id']} — data synced to aetherforge"
    return merged


def write_local_nexus_files(wave: Dict[str, Any]) -> Dict[str, Path]:
    """Persist wave locally for inspection and offline push."""
    LOCAL_NEXUS_DIR.mkdir(parents=True, exist_ok=True)
    paths = {}
    factory_path = LOCAL_NEXUS_DIR / "rsi-eaf-factory.json"
    factory_path.write_text(json.dumps(wave, indent=2), encoding="utf-8")
    paths["rsi_eaf_factory"] = factory_path

    nexus_existing = _fetch_repo_json("nexus_data.json")
    merged_nexus = merge_nexus_data(nexus_existing, wave)
    nexus_path = LOCAL_NEXUS_DIR / "nexus_data.json"
    nexus_path.write_text(json.dumps(merged_nexus, indent=2), encoding="utf-8")
    paths["nexus_data"] = nexus_path

    control_existing = _fetch_repo_json("control-state.json")
    merged_control = merge_control_state(control_existing, wave)
    control_path = LOCAL_NEXUS_DIR / "control-state.json"
    control_path.write_text(json.dumps(merged_control, indent=2), encoding="utf-8")
    paths["control_state"] = control_path
    return paths


def verify_external_surfaces() -> Dict[str, Any]:
    """ASI Tier 1: confirm live aetherforge + factory Vercel surfaces."""
    results: Dict[str, Any] = {"timestamp": _now_iso()}
    for label, url in (
        ("aetherforge", AETHERFORGE_URL),
        ("factory_vercel", FACTORY_PUBLIC_BASE_URL),
        ("factory_tip_manifest", f"{FACTORY_PUBLIC_BASE_URL}/tip-manifest.json"),
    ):
        ok = verify_live_url(url)
        results[label] = {"url": url, "ok": ok, "status": 200 if ok else "unreachable"}
    results["all_ok"] = all(results[k]["ok"] for k in ("aetherforge", "factory_vercel"))
    return results


def push_nexus_wave(cycle_id: int, wave: Dict[str, Any]) -> Dict[str, Any]:
    """Push merged nexus files to jarvis-swarm → triggers aetherforge Vercel refresh."""
    from tools.github_client import push_files

    message = (
        f"data: RSI-EAF factory cycle {cycle_id} nexus emit "
        f"(net={wave['rsi_eaf_factory']['ledger_net'].get('net_usd_est')})"
    )
    local = write_local_nexus_files(wave)

    files = [
        {"path": "nexus_data.json", "content": local["nexus_data"].read_text(encoding="utf-8")},
        {"path": "control-state.json", "content": local["control_state"].read_text(encoding="utf-8")},
        {"path": "rsi-eaf-factory.json", "content": local["rsi_eaf_factory"].read_text(encoding="utf-8")},
    ]
    batch = push_files(NEXUS_OWNER, NEXUS_REPO, files, message, NEXUS_BRANCH)
    if batch.get("success"):
        results = [batch]
        pushed = [batch]
    else:
        results = [
            push_nexus_file(item["path"], item["content"], message)
            for item in files
        ]
        pushed = [r for r in results if r.get("success")]
    verification = verify_external_surfaces()
    return {
        "emitted": len(pushed) > 0,
        "files_attempted": len(results),
        "files_pushed": len(pushed),
        "results": results,
        "local_paths": {k: str(v) for k, v in local.items()},
        "verification": verification,
        "aetherforge_url": AETHERFORGE_URL,
        "jarvis_swarm_repo": f"https://github.com/{NEXUS_OWNER}/{NEXUS_REPO}",
    }


def maybe_emit_nexus(
    cycle_result: Dict[str, Any],
    *,
    force: bool = False,
    factory_state: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Emit factory observability to aetherforge via jarvis-swarm GitHub push.
    Runs every N cycles (default 1) when NEXUS_EMIT_ENABLED.
    """
    if not _nexus_emit_enabled():
        return {"emitted": False, "skipped": True, "reason": "NEXUS_EMIT_DISABLED"}

    from tools.github_ci_gate import block_distribution_if_ci_red

    nexus_ci_owner = os.getenv("NEXUS_CI_GATE_OWNER", NEXUS_OWNER)
    nexus_ci_repo = os.getenv("NEXUS_CI_GATE_REPO", NEXUS_REPO)
    ci_block = block_distribution_if_ci_red(
        owner=nexus_ci_owner,
        repo=nexus_ci_repo,
    )
    if ci_block and not force:
        return {"emitted": False, "skipped": True, "reason": ci_block, "ci_blocked": True}

    cycle_id = int(cycle_result.get("cycle_id", 0))
    every_n = _nexus_emit_every_n()
    due = force or (cycle_id % every_n == 0)
    if not due:
        return {
            "emitted": False,
            "skipped": True,
            "reason": f"not due (every {every_n} cycles)",
        }

    wave = assemble_factory_wave(cycle_result)
    push_result = push_nexus_wave(cycle_id, wave)

    if factory_state is not None and hasattr(factory_state, "set_nexus_emit"):
        factory_state.set_nexus_emit({
            "cycle_id": cycle_id,
            "emitted": push_result.get("emitted"),
            "aetherforge_url": AETHERFORGE_URL,
            "verification": push_result.get("verification"),
        })

    return {
        "due": due,
        "wave_id": wave["wave_id"],
        **push_result,
    }


def run_platform_sync(
    cycle_result: Dict[str, Any],
    *,
    force_github: bool = False,
    force_nexus: bool = False,
    factory_state: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Unified GitHub + Vercel verify + aetherforge nexus sync for end-of-cycle.
    """
    from tools.github_distribution import maybe_push_distribution

    cycle_id = int(cycle_result.get("cycle_id", 0))
    execution = cycle_result.get("execution", {})
    featured = execution.get("featured_surfaces", {})
    treasury = execution.get("treasury_address", "")

    github_result = maybe_push_distribution(
        cycle_id=cycle_id,
        featured=featured,
        treasury_address=treasury,
        force=force_github,
        factory_state=factory_state,
    )
    jarvis_ci_repair = {}
    try:
        from tools.jarvis_swarm_ci_repair import maybe_repair_nexus_ci

        jarvis_ci_repair = maybe_repair_nexus_ci(cycle_id, force=force_nexus)
    except Exception as exc:
        jarvis_ci_repair = {"error": str(exc)}

    nexus_result = maybe_emit_nexus(
        cycle_result,
        force=force_nexus or force_github,
        factory_state=factory_state,
    )
    vercel_status = {
        "cooldown": deploy_cooldown_status(),
        "live_url": execution.get("live_url") or FACTORY_PUBLIC_BASE_URL,
        "live_verified": execution.get("live_verified"),
    }
    return {
        "cycle_id": cycle_id,
        "github": github_result,
        "jarvis_ci_repair": jarvis_ci_repair,
        "nexus": nexus_result,
        "vercel": vercel_status,
        "surfaces": verify_external_surfaces(),
    }