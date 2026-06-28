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

def _resolve_grok_bin() -> str:
    explicit = os.getenv("GROK_BIN")
    if explicit:
        return explicit
    which = shutil.which("grok")
    if which:
        return which
    for candidate in (
        os.path.expanduser("~/.grok/bin/grok"),
        os.path.expanduser("~/.grok/bin/grok.exe"),
    ):
        if Path(candidate).exists():
            return candidate
    return ""


GROK_BIN = _resolve_grok_bin()
ACP_ENABLED = os.getenv("GROK_ORCHESTRATION", "subprocess").lower() == "acp"
ACP_TIMEOUT = int(os.getenv("GROK_ACP_TIMEOUT_SEC", "300"))
ACP_HEARTBEAT = os.getenv("GROK_ACP_HEARTBEAT", "true").lower() in {"1", "true", "yes"}


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


def init_runner_acp(factory_state: Optional[Any] = None) -> Dict[str, Any]:
    """Boot persistent ACP session for autonomous_runner loop."""
    if not ACP_ENABLED:
        return {"started": False, "reason": "acp_disabled"}
    client = get_acp_client()
    start = client.start()
    if start.get("started") and factory_state is not None and hasattr(factory_state, "set_acp_session"):
        factory_state.set_acp_session({
            "session_id": start.get("session_id"),
            "mode": "runner",
            "reused": start.get("reused", False),
        })
    return {"client": client, **start}


def shutdown_runner_acp(client: Optional[GrokACPClient] = None) -> None:
    """Terminate ACP stdio process and clear singleton."""
    global _acp_singleton
    target = client or _acp_singleton
    if target:
        target.close()
    _acp_singleton = None


def runner_acp_heartbeat(
    cycle_id: int,
    cycle_result: Dict[str, Any],
    factory_state: Optional[Any] = None,
) -> Dict[str, Any]:
    """Post-cycle ACP prompt to keep runner session context warm."""
    if not ACP_ENABLED or not ACP_HEARTBEAT:
        return {"skipped": True, "reason": "acp_heartbeat_disabled"}
    net = cycle_result.get("ledger_net", {})
    analysis = cycle_result.get("analysis", {})
    prompt = (
        f"RSI-EAF cycle {cycle_id} runner heartbeat.\n"
        f"net={net.get('net_usd_est')} organic={net.get('organic_revenue_usd_est')} "
        f"focus={analysis.get('cycle_focus')} revenue={analysis.get('cycle_revenue_usd', 0)}\n"
        'Return JSON: {"observation":"","revenue_action":""}'
    )
    return run_cycle_via_acp(cycle_id, prompt, factory_state=factory_state)