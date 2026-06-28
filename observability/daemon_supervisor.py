"""
Factory daemon supervisor — register, heartbeat, and status for background services.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

STATUS_FILE = Path(os.getenv("DAEMON_STATUS_FILE", "observability/daemon_status.json"))
_lock = threading.Lock()
_registry: Dict[str, Dict[str, Any]] = {}


def register_daemon(name: str, start_fn: Callable[[], Dict[str, Any]]) -> Dict[str, Any]:
    """Start a named daemon once; record status."""
    with _lock:
        existing = _registry.get(name, {})
        if existing.get("started"):
            return {"started": False, "reason": "already_running", "name": name, **existing}

        result = start_fn()
        entry = {
            "name": name,
            "started": bool(result.get("started")),
            "started_at": datetime.now(timezone.utc).isoformat(),
            "last_heartbeat": datetime.now(timezone.utc).isoformat(),
            "meta": result,
        }
        _registry[name] = entry
        _persist()
        return entry


def heartbeat(name: str, extra: Optional[Dict[str, Any]] = None) -> None:
    with _lock:
        if name not in _registry:
            return
        _registry[name]["last_heartbeat"] = datetime.now(timezone.utc).isoformat()
        if extra:
            _registry[name]["meta"] = {**_registry[name].get("meta", {}), **extra}
        _persist()


def daemon_status() -> Dict[str, Any]:
    with _lock:
        return {"daemons": list(_registry.values()), "count": len(_registry)}


def start_factory_daemons(treasury_address: Optional[str] = None) -> List[Dict[str, Any]]:
    """Boot all enabled factory daemons."""
    results: List[Dict[str, Any]] = []

    if os.getenv("TREASURY_DAEMON_ENABLED", "true").lower() in {"1", "true", "yes"}:
        from observability.treasury_daemon import start_treasury_daemon

        results.append(
            register_daemon(
                "treasury_ws",
                lambda: start_treasury_daemon(treasury_address),
            )
        )
    return results


def _persist() -> None:
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "daemons": list(_registry.values()),
    }
    STATUS_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")