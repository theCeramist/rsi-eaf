"""
XRPL network control plane for RSI-EAF.

Professional dual-network posture for first real (mainnet) revenue:

  XRPL_NETWORK          testnet | mainnet | dual   (default: dual once mainnet treasury exists)
  XRPL_OPS_NETWORK      network used for internal anchors / factory outbound (default: testnet)
  XRPL_REVENUE_NETWORK  network advertised on pay surfaces (default: mainnet when ready else testnet)
  MAINNET_OUTBOUND_ENABLED  must be true to send real XRP (default: false)
  MAINNET_MAX_OUTBOUND_XRP  hard cap per outbound payment (default: 0.05)

Public pay surfaces use resolve_public_treasury().
Internal cycle anchors use resolve_ops_network() + testnet treasury.

Never commit seeds. Never print full seeds.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

OBS = Path(os.getenv("MAINNET_READINESS_DIR", "observability"))
READY_FILE = OBS / "mainnet_readiness.json"
PUB = Path(os.getenv("PUBLISHED_DIR", "published"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def network_mode() -> str:
    """Overall factory network mode."""
    mode = (os.getenv("XRPL_NETWORK") or "").strip().lower()
    if mode in {"testnet", "mainnet", "dual"}:
        return mode
    # Auto dual when mainnet treasury is configured
    if mainnet_treasury_address():
        return "dual"
    return "testnet"


def ops_network() -> str:
    """Network for factory outbound anchors / operator wallet."""
    n = (os.getenv("XRPL_OPS_NETWORK") or "").strip().lower()
    if n in {"testnet", "mainnet"}:
        return n
    mode = network_mode()
    if mode == "mainnet":
        return "mainnet"
    return "testnet"


def revenue_network() -> str:
    """Network advertised for external payer conversion. Never blocks on RPC."""
    n = (os.getenv("XRPL_REVENUE_NETWORK") or "").strip().lower()
    if n in {"testnet", "mainnet"}:
        return n
    mode = network_mode()
    if mode == "mainnet":
        return "mainnet"
    if mode == "dual" and mainnet_treasury_address():
        # Prefer mainnet address even before first inbound (account may activate on first pay)
        prefer = (os.getenv("XRPL_PREFER_MAINNET_REVENUE", "true").lower() in {"1", "true", "yes"})
        if prefer:
            return "mainnet"
    return "testnet"


def is_testnet(network: Optional[str] = None) -> bool:
    return (network or ops_network()) != "mainnet"


def rpc_url(network: str) -> str:
    if network == "mainnet":
        return os.getenv("XRPL_MAINNET_URL", "https://xrplcluster.com/")
    return os.getenv("XRPL_TESTNET_URL", "https://s.altnet.rippletest.net:51234")


def ws_url(network: str) -> str:
    if network == "mainnet":
        return os.getenv("XRPL_MAINNET_WS_URL", "wss://xrplcluster.com/")
    return os.getenv(
        "XRPL_TESTNET_WS_URL",
        os.getenv("XRPL_TESTNET_WS", "wss://s.altnet.rippletest.net:51233"),
    )


def explorer_tx_url(tx_hash: str, network: str) -> str:
    if not tx_hash:
        return ""
    if network == "mainnet":
        return f"https://xrpl.org/transactions/{tx_hash}"
    return f"https://testnet.xrpl.org/transactions/{tx_hash}"


def explorer_account_url(address: str, network: str) -> str:
    if network == "mainnet":
        return f"https://xrpl.org/accounts/{address}"
    return f"https://testnet.xrpl.org/accounts/{address}"


def network_label(network: str) -> str:
    return "xrpl_mainnet" if network == "mainnet" else "xrpl_testnet"


def testnet_treasury_address() -> str:
    return (
        os.getenv("FACTORY_TREASURY_ADDRESS")
        or os.getenv("TESTNET_TREASURY_ADDRESS")
        or ""
    ).strip()


def mainnet_treasury_address() -> str:
    return (
        os.getenv("FACTORY_MAINNET_TREASURY_ADDRESS")
        or os.getenv("MAINNET_TREASURY_ADDRESS")
        or ""
    ).strip()


def resolve_public_treasury() -> Tuple[str, str]:
    """
    Treasury + network for public pay surfaces (what social CTAs should use).
    Returns (address, network) where network is 'testnet' | 'mainnet'.
    """
    rev = revenue_network()
    if rev == "mainnet":
        addr = mainnet_treasury_address()
        if addr:
            return addr, "mainnet"
    addr = testnet_treasury_address()
    if addr:
        return addr, "testnet"
    # last resort factory address
    fallback = (os.getenv("FACTORY_XRPL_ADDRESS") or "").strip()
    return fallback, "testnet"


def resolve_ops_treasury() -> Tuple[str, str]:
    """Treasury for internal test anchors (usually testnet)."""
    ops = ops_network()
    if ops == "mainnet":
        addr = mainnet_treasury_address() or testnet_treasury_address()
        return addr, "mainnet"
    return testnet_treasury_address(), "testnet"


def treasury_watch_targets() -> List[Dict[str, str]]:
    """Addresses the factory must listen on for inbound revenue."""
    targets: List[Dict[str, str]] = []
    seen = set()
    tn = testnet_treasury_address()
    if tn and ("testnet", tn) not in seen:
        targets.append({"network": "testnet", "address": tn, "role": "testnet_treasury"})
        seen.add(("testnet", tn))
    mn = mainnet_treasury_address()
    if mn and ("mainnet", mn) not in seen:
        targets.append({"network": "mainnet", "address": mn, "role": "mainnet_treasury"})
        seen.add(("mainnet", mn))
    # If dual and only one configured, still watch ops factory address on ops net
    mode = network_mode()
    if mode in {"dual", "mainnet"} and mn:
        pass
    return targets


def mainnet_outbound_allowed(amount_xrp: float) -> Dict[str, Any]:
    """Hard safety gate for spending real XRP."""
    if not _env_bool("MAINNET_OUTBOUND_ENABLED", False):
        return {
            "allowed": False,
            "reason": "MAINNET_OUTBOUND_ENABLED=false — mainnet spend blocked",
        }
    try:
        cap = float(os.getenv("MAINNET_MAX_OUTBOUND_XRP", "0.05") or "0.05")
    except ValueError:
        cap = 0.05
    if float(amount_xrp) > cap:
        return {
            "allowed": False,
            "reason": f"amount {amount_xrp} exceeds MAINNET_MAX_OUTBOUND_XRP={cap}",
            "cap": cap,
        }
    return {"allowed": True, "cap": cap}


def is_mainnet_revenue_ready(*, strict: bool = True) -> Dict[str, Any]:
    """
    Checklist for advertising mainnet as the primary revenue path.
    strict=True requires live account (activated on ledger).
    """
    checks: Dict[str, Any] = {}
    addr = mainnet_treasury_address()
    checks["mainnet_treasury_configured"] = bool(addr and re.match(r"^r[1-9A-HJ-NP-Za-km-z]{24,34}$", addr))
    checks["mainnet_treasury_address"] = addr or None
    checks["seed_configured"] = bool(
        (os.getenv("FACTORY_MAINNET_TREASURY_SEED") or os.getenv("MAINNET_TREASURY_SEED") or "").strip()
    )
    checks["outbound_disabled_by_default"] = not _env_bool("MAINNET_OUTBOUND_ENABLED", False)
    checks["ops_isolated"] = ops_network() == "testnet" or _env_bool("MAINNET_OUTBOUND_ENABLED", False)

    account_ok = False
    balance_xrp = None
    account_error = None
    if checks["mainnet_treasury_configured"]:
        try:
            import httpx

            url = rpc_url("mainnet")
            r = httpx.post(
                url,
                json={"method": "account_info", "params": [{"account": addr, "ledger_index": "validated"}]},
                timeout=8.0,
            )
            body = r.json() if r.content else {}
            result = (body or {}).get("result") or {}
            if result.get("status") == "success" and result.get("account_data"):
                drops = result["account_data"].get("Balance")
                balance_xrp = float(drops) / 1_000_000.0 if drops is not None else 0.0
                account_ok = True
                checks["account_activated"] = True
                checks["balance_xrp"] = balance_xrp
            else:
                # actNotFound / unfunded — still receivable after first pay
                account_error = str(result.get("error_message") or result.get("error") or "unfunded")[:200]
                checks["account_activated"] = False
                checks["account_error"] = account_error
                account_ok = not strict
        except Exception as exc:
            account_error = str(exc)[:200]
            checks["account_activated"] = False
            checks["account_error"] = account_error
            account_ok = not strict

    checks["rpc_mainnet_reachable"] = False
    try:
        import httpx

        url = rpc_url("mainnet")
        # Fast JSON-RPC probe with hard timeout (avoid hanging factory cycles)
        payload = {"method": "server_info", "params": [{}]}
        r = httpx.post(url, json=payload, timeout=8.0)
        body = r.json() if r.content else {}
        checks["rpc_mainnet_reachable"] = r.status_code == 200 and "result" in (body or {})
        checks["server_info_ok"] = checks["rpc_mainnet_reachable"]
    except Exception as exc:
        checks["rpc_error"] = str(exc)[:200]

    ready = bool(
        checks["mainnet_treasury_configured"]
        and checks["rpc_mainnet_reachable"]
        and checks["outbound_disabled_by_default"]
        and (checks.get("account_activated") or not strict)
    )
    return {
        "ready": ready,
        "strict": strict,
        "checks": checks,
        "public_network": revenue_network(),
        "ops_network": ops_network(),
        "mode": network_mode(),
        "explorer": explorer_account_url(addr, "mainnet") if addr else None,
        "at": _now(),
    }


def write_readiness_artifacts(cycle_id: int = 0) -> Dict[str, Any]:
    """Persist readiness for ops + publish slim public status (no secrets)."""
    report = is_mainnet_revenue_ready(strict=False)
    report_strict = is_mainnet_revenue_ready(strict=True)
    pub_treasury, pub_net = resolve_public_treasury()
    payload = {
        "schema": "rsi_eaf_mainnet_readiness_v1",
        "cycle_id": cycle_id,
        "at": _now(),
        "ready_accept_unfunded": report,
        "ready_strict_activated": report_strict,
        "public_treasury": pub_treasury,
        "public_network": pub_net,
        "watch_targets": treasury_watch_targets(),
        "safety": {
            "mainnet_outbound_enabled": _env_bool("MAINNET_OUTBOUND_ENABLED", False),
            "mainnet_max_outbound_xrp": float(os.getenv("MAINNET_MAX_OUTBOUND_XRP", "0.05") or 0.05),
            "ops_network": ops_network(),
        },
    }
    OBS.mkdir(parents=True, exist_ok=True)
    READY_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    PUB.mkdir(parents=True, exist_ok=True)
    public = {
        "schema": "rsi_eaf_network_status_v1",
        "updated_at": _now(),
        "cycle_id": cycle_id,
        "revenue_network": pub_net,
        "revenue_network_label": network_label(pub_net),
        "treasury_address": pub_treasury,
        "explorer": explorer_account_url(pub_treasury, pub_net) if pub_treasury else None,
        "mainnet_ready": bool(report.get("ready")),
        "mainnet_account_activated": bool(report_strict.get("checks", {}).get("account_activated")),
        "ops_network": ops_network(),
        "mode": network_mode(),
        "pay_url": f"{os.getenv('FACTORY_PUBLIC_BASE_URL', 'https://published-zeta.vercel.app').rstrip('/')}/pay.html",
        "agent_pay": f"{os.getenv('FACTORY_PUBLIC_BASE_URL', 'https://published-zeta.vercel.app').rstrip('/')}/agent-pay.json",
        "instruction": (
            f"Send XRP on {network_label(pub_net)} to {pub_treasury} with Destination Tag 1 "
            "(no memo required) for a verified tip."
        ),
    }
    (PUB / "network-status.json").write_text(json.dumps(public, indent=2), encoding="utf-8")
    return payload


def ensure_mainnet_treasury_env(env_path: Optional[Path] = None) -> Dict[str, Any]:
    """
    Ensure FACTORY_MAINNET_TREASURY_ADDRESS (+ seed) exist in process env and .env.
    Generates offline wallet if missing. Never logs full seed.
    """
    env_path = env_path or Path(os.getenv("FACTORY_ENV_FILE", ".env"))
    existing_addr = mainnet_treasury_address()
    existing_seed = (
        os.getenv("FACTORY_MAINNET_TREASURY_SEED") or os.getenv("MAINNET_TREASURY_SEED") or ""
    ).strip()
    if existing_addr and existing_seed:
        return {
            "created": False,
            "address": existing_addr,
            "seed_present": True,
            "path": str(env_path),
        }
    if existing_addr and not existing_seed:
        # Address only (receive-only ops) is OK for revenue; seed optional for receive
        return {
            "created": False,
            "address": existing_addr,
            "seed_present": False,
            "path": str(env_path),
            "note": "receive-only treasury (no seed) — valid for inbound revenue",
        }

    from xrpl.wallet import Wallet

    wallet = Wallet.create()
    seed = wallet.seed
    address = wallet.classic_address
    os.environ["FACTORY_MAINNET_TREASURY_SEED"] = seed
    os.environ["FACTORY_MAINNET_TREASURY_ADDRESS"] = address
    os.environ.setdefault("MAINNET_TREASURY_ADDRESS", address)
    os.environ.setdefault("XRPL_NETWORK", "dual")
    os.environ.setdefault("XRPL_OPS_NETWORK", "testnet")
    os.environ.setdefault("XRPL_REVENUE_NETWORK", "mainnet")
    os.environ.setdefault("MAINNET_OUTBOUND_ENABLED", "false")
    os.environ.setdefault("MAINNET_MAX_OUTBOUND_XRP", "0.05")
    os.environ.setdefault("XRPL_PREFER_MAINNET_REVENUE", "true")

    block = (
        "\n# --- XRPL mainnet revenue treasury (auto-generated; never commit) ---\n"
        f"FACTORY_MAINNET_TREASURY_ADDRESS={address}\n"
        f"FACTORY_MAINNET_TREASURY_SEED={seed}\n"
        "MAINNET_TREASURY_ADDRESS=" + address + "\n"
        "XRPL_NETWORK=dual\n"
        "XRPL_OPS_NETWORK=testnet\n"
        "XRPL_REVENUE_NETWORK=mainnet\n"
        "MAINNET_OUTBOUND_ENABLED=false\n"
        "MAINNET_MAX_OUTBOUND_XRP=0.05\n"
        "XRPL_PREFER_MAINNET_REVENUE=true\n"
    )
    try:
        existing = env_path.read_text(encoding="utf-8") if env_path.is_file() else ""
        if "FACTORY_MAINNET_TREASURY_ADDRESS=" not in existing:
            with env_path.open("a", encoding="utf-8") as fh:
                fh.write(block)
        updated = True
    except OSError as exc:
        return {
            "created": True,
            "address": address,
            "seed_present": True,
            "env_write_error": str(exc)[:200],
            "seed_prefix": (seed or "")[:6] + "...",
        }

    # Secure-ish local mirror for recovery (gitignored via observability secrets pattern)
    secret_dir = Path("observability/secrets")
    secret_dir.mkdir(parents=True, exist_ok=True)
    # Ensure secrets dir is gitignored
    gi = Path(".gitignore")
    try:
        gi_text = gi.read_text(encoding="utf-8") if gi.exists() else ""
        if "observability/secrets" not in gi_text:
            with gi.open("a", encoding="utf-8") as fh:
                fh.write("\n# Mainnet wallet material — never commit\nobservability/secrets/\n")
    except OSError:
        pass
    (secret_dir / "mainnet_treasury.json").write_text(
        json.dumps(
            {
                "address": address,
                "seed": seed,
                "created_at": _now(),
                "network": "mainnet",
                "warning": "CONFIDENTIAL — do not commit or share",
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    return {
        "created": True,
        "address": address,
        "seed_present": True,
        "seed_prefix": (seed or "")[:6] + "...",
        "env_updated": updated,
        "path": str(env_path),
    }
