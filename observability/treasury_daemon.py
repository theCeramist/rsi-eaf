"""
Background XRPL treasury WebSocket listener — persistent payment detection between cycles.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

INBOX_FILE = Path(os.getenv("TREASURY_INBOX_FILE", "observability/treasury_inbox.jsonl"))
DEDUPE_FILE = Path(os.getenv("TREASURY_DEDUPE_FILE", "observability/treasury_dedupe.json"))
DAEMON_ENABLED = os.getenv("TREASURY_DAEMON_ENABLED", "true").lower() in {"1", "true", "yes"}
POLL_CHUNK_SEC = float(os.getenv("TREASURY_DAEMON_CHUNK_SEC", "30"))
DEDUPE_WINDOW = int(os.getenv("TREASURY_INBOX_DEDUPE", "200"))

_daemon_thread: Optional[threading.Thread] = None
_daemon_stop = threading.Event()
_inbox_lock = threading.Lock()

_seen_hashes: set[str] = set()


def _load_dedupe() -> None:
    global _seen_hashes
    if not DEDUPE_FILE.exists():
        return
    try:
        data = json.loads(DEDUPE_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            _seen_hashes = set(data[-DEDUPE_WINDOW:])
    except (json.JSONDecodeError, OSError):
        pass


def _persist_dedupe() -> None:
    DEDUPE_FILE.parent.mkdir(parents=True, exist_ok=True)
    DEDUPE_FILE.write_text(json.dumps(sorted(_seen_hashes)[-DEDUPE_WINDOW:]), encoding="utf-8")


def _append_inbox(payment: Dict[str, Any]) -> None:
    tx_hash = payment.get("tx_hash") or payment.get("hash")
    if tx_hash:
        with _inbox_lock:
            if tx_hash in _seen_hashes:
                return
            _seen_hashes.add(tx_hash)
            if len(_seen_hashes) > DEDUPE_WINDOW:
                _seen_hashes.clear()
                _seen_hashes.add(tx_hash)
            _persist_dedupe()
    INBOX_FILE.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payment": payment,
    }
    with _inbox_lock:
        with INBOX_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    try:
        from observability.daemon_supervisor import heartbeat

        heartbeat("treasury_ws", {"last_payment": tx_hash})
    except Exception:
        pass


def drain_inbox(limit: int = 100) -> list[Dict[str, Any]]:
    """Atomically drain pending inbox payments (process-then-delete)."""
    if not INBOX_FILE.exists():
        return []
    with _inbox_lock:
        raw = INBOX_FILE.read_text(encoding="utf-8").strip()
        if not raw:
            return []
        lines = raw.splitlines()
        INBOX_FILE.write_text("", encoding="utf-8")
    entries = []
    for line in lines[-limit:]:
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def _daemon_loop(targets: list) -> None:
    """targets: list of {address, network} where network is testnet|mainnet."""
    from tools.xrpl_tools import monitor_incoming_payments

    desc = ", ".join(f"{t.get('network')}:{t.get('address')}" for t in targets)
    print(f"[TreasuryDaemon] Listening on [{desc}] (chunk {POLL_CHUNK_SEC}s)")
    while not _daemon_stop.is_set():
        for t in targets:
            if _daemon_stop.is_set():
                break
            address = t.get("address")
            network = t.get("network") or "testnet"
            if not address:
                continue

            def _cb(payment: Dict[str, Any], _net: str = network, _addr: str = address) -> None:
                payment = dict(payment)
                payment.setdefault("network", _net)
                payment.setdefault("treasury_address", _addr)
                payment.setdefault("revenue_class_hint", "organic" if _net == "mainnet" else None)
                _append_inbox(payment)

            try:
                monitor_incoming_payments(
                    address=address,
                    callback=_cb,
                    testnet=(network != "mainnet"),
                    timeout_seconds=max(5, int(POLL_CHUNK_SEC // max(1, len(targets)))),
                )
            except Exception as exc:
                print(f"[TreasuryDaemon] Error {_net if False else network}/{address}: {exc}")
        if _daemon_stop.wait(2.0):
            break


def is_treasury_daemon_running() -> bool:
    return _daemon_thread is not None and _daemon_thread.is_alive()


def start_treasury_daemon(treasury_address: Optional[str] = None) -> Dict[str, Any]:
    """Start background WS listener(s) for testnet + mainnet treasuries."""
    global _daemon_thread
    if not DAEMON_ENABLED:
        return {"started": False, "reason": "TREASURY_DAEMON_DISABLED"}

    from tools.xrpl_tools import FACTORY_XRPL_ADDRESS

    targets: list = []
    try:
        from factory_core.xrpl_network import treasury_watch_targets

        for t in treasury_watch_targets():
            targets.append({"address": t["address"], "network": t["network"]})
    except Exception:
        pass

    # Explicit single-address override (legacy)
    if treasury_address:
        # Prefer mainnet if env says so, else testnet
        net = "mainnet" if os.getenv("XRPL_REVENUE_NETWORK", "").lower() == "mainnet" else "testnet"
        if not any(t["address"] == treasury_address for t in targets):
            targets.append({"address": treasury_address, "network": net})

    if not targets:
        address = os.getenv("FACTORY_TREASURY_ADDRESS") or FACTORY_XRPL_ADDRESS
        if not address:
            return {"started": False, "reason": "no_treasury_address"}
        targets = [{"address": address, "network": "testnet"}]

    if is_treasury_daemon_running():
        return {
            "started": False,
            "reason": "already_running",
            "targets": targets,
            "treasury_address": targets[0]["address"],
        }

    _load_dedupe()
    _daemon_stop.clear()
    _daemon_thread = threading.Thread(
        target=_daemon_loop,
        args=(targets,),
        name="treasury-ws-daemon",
        daemon=True,
    )
    _daemon_thread.start()
    return {
        "started": True,
        "targets": targets,
        "treasury_address": targets[0]["address"],
        "chunk_sec": POLL_CHUNK_SEC,
    }


def daemon_health() -> Dict[str, Any]:
    """Runtime health for treasury WS daemon."""
    alive = _daemon_thread is not None and _daemon_thread.is_alive()
    pending = 0
    if INBOX_FILE.exists():
        with _inbox_lock:
            pending = len([ln for ln in INBOX_FILE.read_text(encoding="utf-8").splitlines() if ln.strip()])
    return {
        "running": alive,
        "inbox_pending": pending,
        "seen_hashes": len(_seen_hashes),
    }


def stop_treasury_daemon() -> None:
    _daemon_stop.set()