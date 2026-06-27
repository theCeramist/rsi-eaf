"""
Persistent factory state for RSI-EAF.

Tracks cycle counter across process restarts. Git-friendly JSON on disk.
"""

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

STATE_FILE = os.getenv("FACTORY_STATE_FILE", "factory_core/factory_state.json")


class FactoryState:
    def __init__(self, state_path: str = STATE_FILE):
        self.state_path = state_path
        os.makedirs(os.path.dirname(state_path) or ".", exist_ok=True)
        self._data = self._load()

    def _load(self) -> Dict[str, Any]:
        if os.path.exists(self.state_path):
            with open(self.state_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"current_cycle": 0, "cycles_completed": 0}

    def _save(self) -> None:
        with open(self.state_path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2)
            f.write("\n")

    @property
    def current_cycle(self) -> int:
        return int(self._data.get("current_cycle", 0))

    def bootstrap_from_ledger(self, max_cycle_id: int) -> None:
        """One-time sync when state file is fresh but ledger has prior cycles."""
        if self.current_cycle == 0 and max_cycle_id > 0:
            self._data["current_cycle"] = max_cycle_id
            self._save()

    def advance_cycle(self) -> int:
        """Increment cycle counter, persist, and return the new cycle id."""
        cycle_id = self.current_cycle + 1
        self._data["current_cycle"] = cycle_id
        self._data["cycles_completed"] = int(self._data.get("cycles_completed", 0)) + 1
        self._data["last_cycle_at"] = datetime.now(timezone.utc).isoformat()
        self._save()
        return cycle_id

    def get_grok_usage_watermark(self) -> Dict[str, Any]:
        return dict(self._data.get("grok_usage_watermark", {}))

    def set_grok_usage_watermark(self, watermark: Dict[str, Any]) -> None:
        self._data["grok_usage_watermark"] = watermark
        self._save()

    def snapshot(self) -> Dict[str, Any]:
        return dict(self._data)