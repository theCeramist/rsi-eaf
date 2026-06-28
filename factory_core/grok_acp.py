"""
Grok ACP client — persistent agent stdio orchestration with subprocess fallback.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

GROK_BIN = os.getenv("GROK_BIN", shutil.which("grok") or os.path.expanduser("~/.grok/bin/grok.exe"))
ACP_ENABLED = os.getenv("GROK_ORCHESTRATION", "subprocess").lower() == "acp"
ACP_TIMEOUT = int(os.getenv("GROK_ACP_TIMEOUT_SEC", "300"))


class GrokACPClient:
    """Minimal JSON-RPC client over `grok agent stdio`."""

    def __init__(self, cwd: Optional[str] = None):
        self.cwd = cwd or os.getcwd()
        self._proc: Optional[subprocess.Popen] = None
        self._session_id: Optional[str] = None
        self._lock = threading.Lock()
        self._request_id = 0

    def _available(self) -> bool:
        return bool(GROK_BIN and Path(GROK_BIN).exists())

    def start(self) -> Dict[str, Any]:
        if not self._available():
            return {"started": False, "reason": "grok_unavailable"}
        if self._proc and self._proc.poll() is None:
            return {"started": True, "session_id": self._session_id, "reused": True}

        try:
            self._proc = subprocess.Popen(
                [GROK_BIN, "agent", "stdio"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=self.cwd,
                bufsize=1,
            )
            init = self._rpc("initialize", {"protocolVersion": "1.0"})
            session = self._rpc("session/new", {"cwd": self.cwd})
            self._session_id = session.get("sessionId") or session.get("session_id")
            return {"started": True, "session_id": self._session_id, "init": init}
        except (OSError, subprocess.SubprocessError) as exc:
            return {"started": False, "error": str(exc)}

    def _rpc(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not self._proc or not self._proc.stdin or not self._proc.stdout:
            return {"error": "not_started"}
        with self._lock:
            self._request_id += 1
            payload = {"jsonrpc": "2.0", "id": self._request_id, "method": method, "params": params or {}}
            self._proc.stdin.write(json.dumps(payload) + "\n")
            self._proc.stdin.flush()
            line = self._proc.stdout.readline()
            if not line:
                return {"error": "no_response"}
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                return {"raw": line.strip()}

    def prompt(self, text: str, cycle_id: Optional[int] = None) -> Dict[str, Any]:
        if not self._session_id:
            start = self.start()
            if not start.get("started"):
                return {"skipped": True, "reason": "acp_start_failed", **start}

        result = self._rpc(
            "session/prompt",
            {"sessionId": self._session_id, "prompt": text, "metadata": {"cycle_id": cycle_id}},
        )
        return {
            "mode": "acp",
            "session_id": self._session_id,
            "cycle_id": cycle_id,
            "result": result,
        }

    def close(self) -> None:
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=5)
            except (subprocess.TimeoutExpired, OSError):
                self._proc.kill()
        self._proc = None


_acp_singleton: Optional[GrokACPClient] = None


def get_acp_client(cwd: Optional[str] = None) -> GrokACPClient:
    global _acp_singleton
    if _acp_singleton is None:
        _acp_singleton = GrokACPClient(cwd=cwd)
    return _acp_singleton


def run_cycle_via_acp(cycle_id: int, prompt: str, factory_state: Optional[Any] = None) -> Dict[str, Any]:
    """Run one factory brain prompt via ACP when GROK_ORCHESTRATION=acp."""
    if not ACP_ENABLED:
        from factory_core.grok_cli import run_headless

        return run_headless(prompt, mode="execute", cycle_id=cycle_id, yolo=True)

    client = get_acp_client()
    result = client.prompt(prompt, cycle_id=cycle_id)
    if factory_state is not None and hasattr(factory_state, "set_acp_session"):
        factory_state.set_acp_session({"session_id": client._session_id, "cycle_id": cycle_id})
    return result