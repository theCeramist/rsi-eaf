"""
Factory daemon supervisor — register, heartbeat, watchdog, and status for background services.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

STATUS_FILE = Path(os.getenv("DAEMON_STATUS_FILE", "observability/daemon_status.json"))
_lock = threading.Lock()
_registry: Dict[str, Dict[str, Any]] = {}
_watchdog_thread: Optional[threading.Thread] = None
_watchdog_stop = threading.Event()

_RESTART_HANDLERS: Dict[str, Callable[[], Dict[str, Any]]] = {}


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
        _RESTART_HANDLERS[name] = start_fn
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


def _daemon_stale_seconds(name: str, entry: Dict[str, Any]) -> float:
    meta = entry.get("meta") or {}
    interval = float(meta.get("interval_sec") or meta.get("chunk_sec") or 300)
    threshold = float(os.getenv("DAEMON_STALE_MULTIPLIER", "3")) * interval
    try:
        last = datetime.fromisoformat(entry.get("last_heartbeat", "").replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - last).total_seconds()
        return age - threshold
    except (ValueError, TypeError):
        return 0.0


def _watchdog_loop() -> None:
    while not _watchdog_stop.wait(float(os.getenv("DAEMON_WATCHDOG_INTERVAL_SEC", "120"))):
        with _lock:
            entries = list(_registry.items())
        for name, entry in entries:
            if not entry.get("started"):
                continue
            if _daemon_stale_seconds(name, entry) <= 0:
                continue
            restart_fn = _RESTART_HANDLERS.get(name)
            if not restart_fn:
                continue
            try:
                if name == "treasury_ws":
                    from observability.treasury_daemon import stop_treasury_daemon

                    stop_treasury_daemon()
                elif name == "distribution":
                    from observability.distribution_daemon import stop_distribution_daemon

                    stop_distribution_daemon()
                result = restart_fn()
                heartbeat(name, {"watchdog_restart": True, **result})
            except Exception as exc:
                heartbeat(name, {"watchdog_error": str(exc)})


def start_daemon_watchdog() -> Dict[str, Any]:
    global _watchdog_thread
    if os.getenv("DAEMON_WATCHDOG_ENABLED", "true").lower() not in {"1", "true", "yes"}:
        return {"started": False, "reason": "disabled"}
    if _watchdog_thread and _watchdog_thread.is_alive():
        return {"started": True, "reason": "already_running"}
    _watchdog_stop.clear()
    _watchdog_thread = threading.Thread(target=_watchdog_loop, name="daemon-watchdog", daemon=True)
    _watchdog_thread.start()
    return {"started": True}


def stop_all_factory_daemons() -> None:
    _watchdog_stop.set()
    stops = [
        ("treasury_ws", "observability.treasury_daemon", "stop_treasury_daemon"),
        ("distribution", "observability.distribution_daemon", "stop_distribution_daemon"),
        ("xrpl_intel", "observability.xrpl_intel_daemon", "stop_xrpl_intel_daemon"),
        ("nexus_echo", "observability.nexus_echo_daemon", "stop_nexus_echo_daemon"),
        ("ci_babysitter", "observability.ci_babysitter_daemon", "stop_ci_babysitter_daemon"),
    ]
    for name, module, fn_name in stops:
        try:
            import importlib

            mod = importlib.import_module(module)
            getattr(mod, fn_name)()
            heartbeat(name, {"stopped": True})
        except Exception:
            pass


def _persist() -> None:
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "daemons": list(_registry.values()),
    }
    STATUS_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")