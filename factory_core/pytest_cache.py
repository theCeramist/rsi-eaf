"""
Per-cycle pytest result cache — avoid duplicate full test runs in hybrid cycles.

Continuous mode reuses a recent passing tool-gate across N cycles so revenue
work is not blocked by a 3–7 minute full suite every cycle.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

_cache: Dict[int, Dict[str, Any]] = {}
_DISK_CACHE = Path(
    os.getenv("FACTORY_PYTEST_CACHE_FILE", "observability/pytest_gate_cache.json")
)


def set_pytest_result(cycle_id: int, result: Dict[str, Any]) -> None:
    payload = dict(result)
    payload["_cached_at_cycle"] = cycle_id
    payload["_cached_at_ts"] = time.time()
    _cache[cycle_id] = payload
    try:
        _DISK_CACHE.parent.mkdir(parents=True, exist_ok=True)
        _DISK_CACHE.write_text(json.dumps(payload, default=str), encoding="utf-8")
    except OSError:
        pass


def get_pytest_result(cycle_id: int) -> Optional[Dict[str, Any]]:
    return _cache.get(cycle_id)


def clear_before_cycle(cycle_id: int) -> None:
    stale = [cid for cid in _cache if cid < cycle_id - 2]
    for cid in stale:
        _cache.pop(cid, None)


def _continuous() -> bool:
    return os.getenv("FACTORY_RUN_CONTINUOUS", "").lower() in {"1", "true", "yes"}


def tool_gate_pytest_every_n() -> int:
    """
    How often to re-run full tool-gate pytest.
    Continuous default: every 3 cycles. Otherwise every cycle (1).
    """
    default = "3" if _continuous() else "1"
    try:
        n = int(os.getenv("TOOL_GATE_PYTEST_EVERY_N", default))
    except ValueError:
        n = 3 if _continuous() else 1
    return max(1, n)


def load_disk_pytest_result() -> Optional[Dict[str, Any]]:
    if not _DISK_CACHE.exists():
        return None
    try:
        data = json.loads(_DISK_CACHE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def get_reusable_pytest_result(cycle_id: int) -> Optional[Dict[str, Any]]:
    """
    Return a recent passing pytest result when skip is allowed for this cycle.
    """
    every_n = tool_gate_pytest_every_n()
    if every_n <= 1:
        return None
    if os.getenv("TOOL_GATE_FORCE_PYTEST", "").lower() in {"1", "true", "yes"}:
        return None

    candidates: list[Dict[str, Any]] = []
    for cid, res in _cache.items():
        if not isinstance(res, dict) or res.get("reused"):
            # Reused stamps must not refresh the watermark or we never re-run.
            continue
        candidates.append({**res, "_cached_at_cycle": res.get("_cached_at_cycle", cid)})
    disk = load_disk_pytest_result()
    if disk and not disk.get("reused"):
        candidates.append(disk)

    best: Optional[Dict[str, Any]] = None
    best_cid = -1
    for res in candidates:
        if not res.get("passed"):
            continue
        try:
            cid = int(res.get("_cached_at_cycle") or res.get("cycle_id") or -1)
        except (TypeError, ValueError):
            cid = -1
        if cid > best_cid:
            best = res
            best_cid = cid

    if best is None or best_cid < 0:
        return None

    age = int(cycle_id) - best_cid
    if age < 0 or age >= every_n:
        return None

    reused = dict(best)
    reused["reused"] = True
    reused["reused_from_cycle"] = best_cid
    reused["reuse_age_cycles"] = age
    return reused
