"""
Persistent factory state for RSI-EAF.

Tracks cycle counter across process restarts. Git-friendly JSON on disk.
"""

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

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

    def get_treasury_watermark(self) -> Dict[str, Any]:
        return dict(self._data.get("treasury_watermark", {}))

    def set_github_distribution(self, urls: Dict[str, Any]) -> None:
        self._data["github_distribution"] = {
            **urls,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._save()

    def get_github_distribution(self) -> Dict[str, Any]:
        return dict(self._data.get("github_distribution", {}))

    def set_nexus_emit(self, payload: Dict[str, Any]) -> None:
        self._data["nexus_emit"] = {
            **payload,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._save()

    def get_nexus_emit(self) -> Dict[str, Any]:
        return dict(self._data.get("nexus_emit", {}))

    def set_gist_distribution(self, payload: Dict[str, Any]) -> None:
        self._data["gist_distribution"] = {
            **payload,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._save()

    def get_gist_distribution(self) -> Dict[str, Any]:
        return dict(self._data.get("gist_distribution", {}))

    def set_release(self, payload: Dict[str, Any]) -> None:
        self._data["github_release"] = {
            **payload,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._save()

    def get_release(self) -> Dict[str, Any]:
        return dict(self._data.get("github_release", {}))

    def set_acp_session(self, payload: Dict[str, Any]) -> None:
        self._data["acp_session"] = {
            **payload,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._save()

    def get_acp_session(self) -> Dict[str, Any]:
        return dict(self._data.get("acp_session", {}))

    def get_implemented_proposals(self) -> List[str]:
        return list(self._data.get("implemented_proposals", []))

    def mark_proposal_implemented(self, title: str) -> None:
        norm = title.strip()
        if not norm:
            return
        implemented = set(self._data.get("implemented_proposals", []))
        implemented.add(norm)
        self._data["implemented_proposals"] = sorted(implemented)
        self._save()

    def set_treasury_watermark(
        self,
        last_ingested_tx_hash: Optional[str] = None,
        last_poll_at: Optional[int] = None,
    ) -> None:
        wm = self.get_treasury_watermark()
        if last_ingested_tx_hash:
            wm["last_ingested_tx_hash"] = last_ingested_tx_hash
        if last_poll_at is not None:
            wm["last_poll_cycle"] = last_poll_at
        wm["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._data["treasury_watermark"] = wm
        self._save()

    def snapshot(self) -> Dict[str, Any]:
        return dict(self._data)