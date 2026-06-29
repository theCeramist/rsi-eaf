"""
Factory health snapshot — merges daemon status, integration manifest, ledger net.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

HEALTH_FILE = Path(os.getenv("FACTORY_HEALTH_FILE", "observability/factory_health.json"))
DAEMON_STATUS_FILE = Path(os.getenv("DAEMON_STATUS_FILE", "observability/daemon_status.json"))


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _fitness_snapshot(cycle_id: int) -> Dict[str, Any]:
    try:
        from observability.factory_fitness_report import generate_factory_fitness_report

        return generate_factory_fitness_report(cycle_id=cycle_id)
    except Exception as exc:
        return {"error": str(exc)}


def build_factory_health(
    cycle_id: int = 0,
    featured: Optional[Dict[str, str]] = None,
    factory_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    from config.integration import integration_manifest
    from observability.economic_ledger import ledger

    try:
        from observability.daemon_supervisor import daemon_status

        daemons = daemon_status()
    except Exception:
        daemons = _read_json(DAEMON_STATUS_FILE)

    net = ledger.calculate_net()
    manifest = integration_manifest(cycle_id=cycle_id, featured=featured or {})

    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "cycle_id": cycle_id,
        "daemons": daemons,
        "ledger_net": net,
        "integration": manifest,
        "factory_state": factory_state or {},
        "organic_revenue_usd": net.get("organic_revenue_usd_est", 0),
        "runner_active": os.getenv("FACTORY_RUNNER_ACTIVE", "").lower() in {"1", "true", "yes"},
        "factory_fitness": _fitness_snapshot(cycle_id),
    }


def persist_factory_health(payload: Optional[Dict[str, Any]] = None, **kwargs: Any) -> Path:
    payload = payload or build_factory_health(**kwargs)
    HEALTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    HEALTH_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return HEALTH_FILE