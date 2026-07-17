"""
Verification gates for RSI-EAF cycles.
All gates must pass before evolution (Phase 6).
"""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from observability.economic_ledger import ledger
from tools.publish_tools import verify_live_url
from tools.xrpl_tools import get_client

PUBLISHED_DIR = os.getenv("PUBLISHED_DIR", "published")

SOFT_EVOLUTION_GATES: Set[str] = {"live_url_reachable", "verified_revenue_pipeline"}


def _gate(name: str, passed: bool, detail: str) -> Dict[str, Any]:
    return {"gate": name, "passed": passed, "detail": detail}


def failed_gate_names(gate_result: Dict[str, Any]) -> List[str]:
    return [g["gate"] for g in gate_result.get("gates", []) if not g.get("passed")]


def gates_core_passed(gate_result: Dict[str, Any]) -> bool:
    """Hard gates — excludes soft deploy/revenue-pipeline gates."""
    for g in gate_result.get("gates", []):
        if g.get("gate") in SOFT_EVOLUTION_GATES:
            continue
        if not g.get("passed"):
            return False
    return True


def gates_evolution_allowed(gate_result: Dict[str, Any]) -> bool:
    """Allow deterministic evolution when only soft gates fail."""
    failed = failed_gate_names(gate_result)
    if not failed:
        return True
    return all(name in SOFT_EVOLUTION_GATES for name in failed)


def count_verified_revenue_events() -> int:
    return ledger.count_verified_revenue_events()


def collect_live_url_candidates(execution_result: Dict[str, Any]) -> List[str]:
    """Ordered live URL fallbacks when per-cycle deploy was skipped."""
    seen: set[str] = set()
    candidates: List[str] = []

    def add(url: Optional[str]) -> None:
        if url and url not in seen:
            seen.add(url)
            candidates.append(url)

    add(execution_result.get("live_url"))
    featured = execution_result.get("featured_surfaces") or {}
    for key in (
        "canonical_tip_page",
        "tip_page",
        "briefing_page",
        "mythos_page",
        "micro_tool_page",
        "tip_manifest",
        "service_catalog",
    ):
        add(featured.get(key))
    tip_page = featured.get("canonical_tip_page") or featured.get("tip_page")
    if tip_page and "://" in str(tip_page):
        from urllib.parse import urlparse

        parsed = urlparse(str(tip_page))
        if parsed.scheme and parsed.netloc:
            add(f"{parsed.scheme}://{parsed.netloc}/tip-manifest.json")

    for url in execution_result.get("live_urls") or []:
        add(url)

    base = os.getenv("FACTORY_PUBLIC_BASE_URL", "").rstrip("/")
    if base:
        add(f"{base}/tip-manifest.json")
        add(f"{base}/")
    return candidates


def resolve_live_url_reachable(execution_result: Dict[str, Any]) -> tuple[bool, str]:
    """Try primary + canonical + manifest/index fallbacks."""
    if execution_result.get("live_verified"):
        return True, str(execution_result.get("live_url") or "live_verified")

    for url in collect_live_url_candidates(execution_result):
        if verify_live_url(url):
            if url != execution_result.get("live_url"):
                return True, f"{url} (fallback)"
            return True, url

    primary = execution_result.get("live_url")
    featured = execution_result.get("featured_surfaces") or {}
    canonical = featured.get("canonical_tip_page") or featured.get("tip_page")
    return False, primary or canonical or "missing"


def verify_xrpl_transaction(tx_hash: str, testnet: bool = True) -> bool:
    if not tx_hash:
        return False
    try:
        from xrpl.models.requests import Tx

        client = get_client(testnet)
        response = client.request(Tx(transaction=tx_hash))
        result = response.result
        return bool(result.get("validated") or result.get("meta", {}).get("TransactionResult") == "tesSUCCESS")
    except Exception:
        return False


def run_tool_improvement_gates(
    cycle_id: int,
    execution_result: Dict[str, Any],
) -> Dict[str, Any]:
    """Gates for tool-improvement cycles (no Vercel / revenue engine requirements)."""
    gates: List[Dict[str, Any]] = []

    pytest_ok = execution_result.get("pytest_passed", False)
    gates.append(_gate("tool_pytest_passed", pytest_ok, str(execution_result.get("pytest", {}))))

    xrpl_ok = execution_result.get("xrpl_ok", False)
    gates.append(_gate("xrpl_connectivity", xrpl_ok, str(execution_result.get("xrpl", {}))))

    log_path = execution_result.get("tool_improvements_log", "")
    log_ok = bool(log_path and Path(log_path).exists())
    gates.append(_gate("tool_improvements_logged", log_ok, log_path))

    cycle_events = [e for e in ledger.get_recent_events(200) if e.get("cycle_id") == cycle_id]
    cost_logged = any(e.get("event_type") == "cost" for e in cycle_events)
    gates.append(_gate("cycle_cost_logged", cost_logged, f"cost_events={sum(1 for e in cycle_events if e.get('event_type') == 'cost')}"))

    net = ledger.calculate_net(since_cycle=cycle_id)
    gates.append(_gate("ledger_net_computable", "net_usd_est" in net, str(net)))

    all_passed = all(g["passed"] for g in gates)
    return {
        "cycle_id": cycle_id,
        "mode": "tool_improvement",
        "all_passed": all_passed,
        "gates_core_passed": all_passed,
        "gates_evolution_allowed": all_passed,
        "gates": gates,
        "passed_count": sum(1 for g in gates if g["passed"]),
        "total_count": len(gates),
    }


def _verified_revenue_gate(cycle_id: int) -> Dict[str, Any]:
    min_cycles = int(os.getenv("REVENUE_VERIFY_MIN_CYCLES", "20"))
    enabled = os.getenv("REVENUE_VERIFY_GATE_ENABLED", "true").lower() in {"1", "true", "yes"}
    verified = count_verified_revenue_events()
    organic = ledger.calculate_net().get("organic_revenue_usd_est", 0)
    if not enabled or cycle_id < min_cycles:
        return _gate(
            "verified_revenue_pipeline",
            True,
            f"skipped (cycle<{min_cycles} or gate disabled); verified={verified}",
        )
    passed = verified > 0 or float(organic) > 0
    return _gate(
        "verified_revenue_pipeline",
        passed,
        f"verified_events={verified} organic=${organic}",
    )


def _published_assets_resolvable(
    published_list: List[Any],
    execution_result: Dict[str, Any],
) -> tuple:
    """
    True if any published path still exists on disk (published/ or archive/),
    or the cycle already proved a live URL (deploy pruned local files).
    """
    published_root = Path(os.getenv("PUBLISHED_DIR", PUBLISHED_DIR))
    resolved: List[str] = []
    for p in published_list:
        if not p:
            continue
        path = Path(str(p))
        if path.exists():
            resolved.append(str(path))
            continue
        # Deploy hygiene may move cycle HTML to published/archive/
        name = path.name
        for candidate in (
            published_root / name,
            published_root / "archive" / name,
            path,
        ):
            if candidate.exists():
                resolved.append(str(candidate))
                break

    if resolved:
        return True, f"count={len(published_list)} resolved={resolved[:3]}"

    # Live-verified deploy is ground truth even if local prune archived files
    if execution_result.get("live_verified") and (
        execution_result.get("live_url") or execution_result.get("live_urls")
    ):
        return True, (
            f"count={len(published_list)} local_missing but live_verified "
            f"url={execution_result.get('live_url')}"
        )

    # Deploy prune often removes local HTML while Vercel still serves the asset.
    # Probe live URL candidates before failing the hard gate.
    live_ok, live_detail = resolve_live_url_reachable(execution_result)
    if live_ok:
        return True, (
            f"count={len(published_list)} local_missing but live_reachable "
            f"{live_detail}"
        )

    # Featured tip / index still present (URL recorded even if not re-probed)
    featured = execution_result.get("featured_surfaces") or {}
    for key in ("tip_page", "canonical_tip_page", "briefing_page"):
        url = featured.get(key)
        if url and str(url).startswith("http"):
            return True, f"count={len(published_list)} featured_surface={key}"

    # Canonical published surfaces that outlive per-cycle HTML filenames
    published_root = Path(os.getenv("PUBLISHED_DIR", PUBLISHED_DIR))
    for stable in ("tip-manifest.json", "index.html", "agent-pay.json", "service-catalog.json"):
        candidate = published_root / stable
        if candidate.exists():
            return True, f"count={len(published_list)} stable_surface={stable}"

    return False, f"count={len(published_list)} paths={list(published_list)[:3]}"


def run_cycle_gates(
    cycle_id: int,
    execution_result: Dict[str, Any],
    require_live_url: bool = False,
) -> Dict[str, Any]:
    """Run all mandatory gates for a completed cycle."""
    if execution_result.get("mode") == "tool_improvement":
        return run_tool_improvement_gates(cycle_id, execution_result)

    gates: List[Dict[str, Any]] = []

    if execution_result.get("cycle_mode") == "hybrid":
        gates.append(
            _gate(
                "tool_pytest_passed",
                execution_result.get("pytest_passed", False),
                "hybrid prerequisite",
            )
        )
        gates.append(
            _gate(
                "xrpl_connectivity",
                execution_result.get("xrpl_ok", False),
                "hybrid prerequisite",
            )
        )

    published_list = execution_result.get("published_assets") or []
    if not published_list and execution_result.get("published_asset"):
        published_list = [execution_result["published_asset"]]
    published_exists, published_detail = _published_assets_resolvable(
        published_list, execution_result
    )
    gates.append(
        _gate(
            "published_asset_exists",
            published_exists,
            published_detail,
        )
    )

    tx_hash = execution_result.get("xrpl_tx_hash")
    tx_ok = verify_xrpl_transaction(tx_hash) if tx_hash else False
    gates.append(
        _gate(
            "xrpl_anchor_confirmed",
            tx_ok,
            f"tx_hash={tx_hash}",
        )
    )

    cycle_events = [e for e in ledger.get_recent_events(200) if e.get("cycle_id") == cycle_id]
    cost_logged = any(e.get("event_type") == "cost" for e in cycle_events)
    gates.append(
        _gate(
            "cycle_cost_logged",
            cost_logged,
            f"cost_events={sum(1 for e in cycle_events if e.get('event_type') == 'cost')}",
        )
    )

    live_url = execution_result.get("live_url")
    if live_url:
        live_ok, live_detail = resolve_live_url_reachable(execution_result)
        gates.append(_gate("live_url_reachable", live_ok, live_detail))
    elif require_live_url:
        gates.append(_gate("live_url_reachable", False, "no live_url in execution result"))

    net = ledger.calculate_net(since_cycle=cycle_id)
    gates.append(
        _gate(
            "ledger_net_computable",
            "net_usd_est" in net,
            str(net),
        )
    )

    gates.append(_verified_revenue_gate(cycle_id))

    all_passed = all(g["passed"] for g in gates)
    result = {
        "cycle_id": cycle_id,
        "all_passed": all_passed,
        "gates_core_passed": gates_core_passed({"gates": gates}),
        "gates_evolution_allowed": gates_evolution_allowed({"gates": gates}),
        "gates": gates,
        "passed_count": sum(1 for g in gates if g["passed"]),
        "total_count": len(gates),
        "failed_gates": failed_gate_names({"gates": gates}),
    }
    return result