"""
Revenue engine registry — run highest-impact generators each cycle.
"""

import os
from pathlib import Path
from typing import Any, Dict, List, Type

from revenue_engines.base_engine import RevenueEngine
from revenue_engines.content_operator import ContentOperator
from revenue_engines.paid_briefing import PaidBriefing
from revenue_engines.tipping_funnel import TippingFunnel

DEFAULT_ENGINES = "content_operator,tipping_funnel,paid_briefing"

_ENGINE_MAP: Dict[str, Type[RevenueEngine]] = {
    "content_operator": ContentOperator,
    "tipping_funnel": TippingFunnel,
    "paid_briefing": PaidBriefing,
}


def enabled_engines() -> List[str]:
    raw = os.getenv("REVENUE_ENGINES", DEFAULT_ENGINES)
    names = [n.strip() for n in raw.split(",") if n.strip()]
    return [n for n in names if n in _ENGINE_MAP]


def run_revenue_engines(cycle_id: int) -> Dict[str, Any]:
    """Execute all enabled engines; single batched Vercel deploy at end."""
    from tools.publish_tools import deploy_to_vercel, resolve_live_url, verify_live_url

    names = enabled_engines()
    results: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []

    os.environ["SKIP_VERCEL_DEPLOY"] = "true"
    try:
        for name in names:
            engine_cls = _ENGINE_MAP[name]
            engine = engine_cls()
            try:
                result = engine.run(cycle_id=cycle_id)
                results.append(result)
            except Exception as exc:
                errors.append({"engine": name, "error": str(exc)})
                print(f"[RevenueRegistry] Engine {name} failed: {exc}")
    finally:
        os.environ.pop("SKIP_VERCEL_DEPLOY", None)

    deploy_result = deploy_to_vercel()
    if deploy_result.get("success") or deploy_result.get("deploy_url"):
        for result in results:
            path = result.get("published_path")
            if path:
                live = resolve_live_url(Path(path).name, deploy_result)
                if live:
                    result["live_url"] = live
                    result["live_verified"] = verify_live_url(live)

    from tools.distribution_tools import canonical_tip_url

    canonical = canonical_tip_url(cycle_id)
    if deploy_result.get("skipped") and canonical:
        for result in results:
            path = result.get("published_path")
            if path:
                result["live_url"] = resolve_live_url(Path(path).name, deploy_result)
                result["live_verified"] = verify_live_url(canonical)

    primary = results[0] if results else {}
    live_urls = [r.get("live_url") for r in results if r.get("live_url")]
    published_assets = [r.get("published_path") for r in results if r.get("published_path")]

    return {
        "engines_run": [r.get("source") for r in results],
        "engine_names": names,
        "results": results,
        "errors": errors,
        "success": len(results) > 0 and len(errors) == 0,
        "primary": primary,
        "published_asset": primary.get("published_path"),
        "published_assets": published_assets,
        "live_url": primary.get("live_url"),
        "live_urls": live_urls,
        "live_verified": any(r.get("live_verified") for r in results),
        "xrpl_tx_hash": primary.get("xrpl_tx_hash"),
        "explorer_url": primary.get("explorer_url"),
        "xrpl_payments_made": sum(1 for r in results if r.get("xrpl_tx_hash")),
        "vercel_deploy": deploy_result,
    }