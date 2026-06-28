"""
Classify verified treasury inflows as organic vs factory-adjacent (test/operator).
"""

import os
from typing import Any, Dict, Optional, Set


def factory_adjacent_wallets() -> Set[str]:
    raw = os.getenv(
        "FACTORY_ADJACENT_WALLETS",
        "rJ2TJZ1KCx6fsshHFVK8MrvNdD1rzyXugJ",
    )
    from tools.xrpl_tools import FACTORY_XRPL_ADDRESS

    wallets = {w.strip() for w in raw.split(",") if w.strip()}
    if FACTORY_XRPL_ADDRESS:
        wallets.add(FACTORY_XRPL_ADDRESS)
    treasury = os.getenv("FACTORY_TREASURY_ADDRESS")
    if treasury:
        wallets.add(treasury)
    return wallets


def classify_inbound_payment(from_address: Optional[str]) -> str:
    """Return 'factory_adjacent' or 'organic'."""
    if from_address and from_address in factory_adjacent_wallets():
        return "factory_adjacent"
    return "organic"


def enrich_revenue_metadata(
    metadata: Optional[Dict[str, Any]],
    from_address: Optional[str],
) -> Dict[str, Any]:
    meta = dict(metadata or {})
    revenue_class = classify_inbound_payment(from_address)
    meta["revenue_class"] = revenue_class
    meta["organic"] = revenue_class == "organic"
    return meta