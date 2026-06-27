"""
Shared primitives for RSI-EAF revenue engines.
"""

import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, Optional

from observability.economic_ledger import ledger
from tools.publish_tools import publish_asset
from tools.xrpl_tools import (
    get_revenue_destination,
    load_factory_wallet,
    send_xrp_payment,
)

PUBLISHED_DIR = os.getenv("PUBLISHED_DIR", "published")
ANCHOR_AMOUNT_XRP = float(os.getenv("REVENUE_ENGINE_ANCHOR_XRP", "0.0001"))
FACTORY_TREASURY_ADDRESS = os.getenv("FACTORY_TREASURY_ADDRESS", "")


def resolve_treasury() -> str:
    treasury = FACTORY_TREASURY_ADDRESS
    if treasury:
        return treasury
    return get_revenue_destination(load_factory_wallet(testnet=True))


def anchor_engine_event(
    source: str,
    cycle_id: int,
    event_type: str,
    notes: str,
    published_path: Path,
    live_url: str = "",
    extra_memo: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    wallet = load_factory_wallet(testnet=True)
    destination = get_revenue_destination(wallet)
    memo_data = {
        "cycle_id": cycle_id,
        "source": source,
        "type": event_type,
        "amount_usd_est": 0.0,
        "notes": notes,
        "published_asset": str(published_path.as_posix()),
        "live_url": live_url or None,
        **(extra_memo or {}),
    }
    payment = send_xrp_payment(
        wallet=wallet,
        destination=destination,
        amount_xrp=ANCHOR_AMOUNT_XRP,
        memo_data=memo_data,
        verbose=True,
    )
    if not payment.get("success"):
        raise RuntimeError(f"XRPL anchoring failed for {source}: {payment}")
    return payment


def publish_and_anchor(
    source: str,
    cycle_id: int,
    html_path: Path,
    treasury: str,
    notes: str,
    event_type: str = "asset_published",
    extra_memo: Optional[Dict[str, Any]] = None,
    extra_metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    publish_result = publish_asset(html_path, treasury_address=treasury)
    live_url = publish_result.get("live_url") or ""

    payment = anchor_engine_event(
        source=source,
        cycle_id=cycle_id,
        event_type=event_type,
        notes=notes,
        published_path=html_path,
        live_url=live_url,
        extra_memo=extra_memo,
    )

    event = ledger.log_event(
        event_type=event_type,
        source=source,
        amount_usd_est=0.0,
        cycle_id=cycle_id,
        xrpl_tx_hash=payment["tx_hash"],
        metadata={
            "notes": notes,
            "published_asset": str(html_path.as_posix()),
            "live_url": live_url,
            "live_verified": publish_result.get("live_verified", False),
            "deploy": publish_result.get("deploy"),
            "treasury_address": treasury,
            "memo": payment.get("memo_data"),
            **(extra_metadata or {}),
        },
        anchor_to_xrpl=False,
    )

    return {
        "success": True,
        "source": source,
        "cycle_id": cycle_id,
        "revenue_usd_est": 0.0,
        "published_path": str(html_path),
        "live_url": live_url,
        "live_verified": publish_result.get("live_verified", False),
        "xrpl_tx_hash": payment["tx_hash"],
        "explorer_url": payment["explorer_url"],
        "ledger_event": event,
        "publish_result": publish_result,
    }


class RevenueEngine(ABC):
    source: str

    @abstractmethod
    def run(self, cycle_id: int) -> Dict[str, Any]:
        """Execute engine and return standardized result dict."""