"""
Per-cycle pytest result cache — avoid duplicate full test runs in hybrid cycles.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

_cache: Dict[int, Dict[str, Any]] = {}


def set_pytest_result(cycle_id: int, result: Dict[str, Any]) -> None:
    _cache[cycle_id] = result


def get_pytest_result(cycle_id: int) -> Optional[Dict[str, Any]]:
    return _cache.get(cycle_id)


def clear_before_cycle(cycle_id: int) -> None:
    stale = [cid for cid in _cache if cid < cycle_id - 2]
    for cid in stale:
        _cache.pop(cid, None)