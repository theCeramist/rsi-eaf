"""
Resolve treasury payment intent — super-simple paths for humans + JSON for agents.

Human-friendly (pick one):
  1. Destination Tag `1` = tip, Tag `2` = briefing unlock (no memo needed)
  2. Plain memo text: `tip` or `briefing` (3–8 chars)
  3. Any external payment with no tag/memo → flat $1 tip (factory policy)

Agents: full JSON memo with type=revenue still supported.
"""

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

TIP_TAG = int(os.getenv("TREASURY_TAG_TIP", "1"))
BRIEFING_TAG = int(os.getenv("TREASURY_TAG_BRIEFING", "2"))
TIP_USD = float(os.getenv("TIP_SUGGESTED_USD", "1.0"))
BRIEFING_USD = float(os.getenv("BRIEFING_UNLOCK_USD", "2.0"))
FLAT_TIP_IF_BLANK = os.getenv("TREASURY_FLAT_TIP_IF_BLANK", "true").lower() in {
    "1",
    "true",
    "yes",
}

TIP_WORDS = {"tip", "support", "donate", "1"}
BRIEFING_WORDS = {"briefing", "unlock", "report", "2"}


@dataclass
class PaymentIntent:
    amount_usd_est: float
    method: str
    notes: str
    product_id: Optional[str] = None
    destination_tag: Optional[int] = None


def _decode_memo_text(hex_data: str) -> Optional[str]:
    try:
        raw = bytes.fromhex(hex_data)
        text = raw.decode("utf-8").strip()
        return text if text else None
    except (ValueError, UnicodeDecodeError):
        return None


def decode_memo_entries(tx: Dict[str, Any]) -> tuple[List[Dict[str, Any]], List[str]]:
    """Return (json_memos, plain_text_memos)."""
    json_memos: List[Dict[str, Any]] = []
    plain_texts: List[str] = []
    for memo_wrap in tx.get("Memos") or []:
        memo = memo_wrap.get("Memo", memo_wrap)
        hex_data = memo.get("MemoData")
        if not hex_data:
            continue
        try:
            parsed = json.loads(bytes.fromhex(hex_data).decode("utf-8"))
            if isinstance(parsed, dict):
                json_memos.append(parsed)
                continue
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
            pass
        text = _decode_memo_text(hex_data)
        if text:
            plain_texts.append(text)
    return json_memos, plain_texts


def resolve_payment_intent(
    payment: Dict[str, Any],
    cycle_id: int,
) -> Optional[PaymentIntent]:
    """
    Map an inbound treasury payment to verified revenue intent, or None.
    """
    tag = payment.get("destination_tag")
    if tag is not None:
        try:
            tag = int(tag)
        except (TypeError, ValueError):
            tag = None

    if tag == TIP_TAG:
        return PaymentIntent(
            amount_usd_est=TIP_USD,
            method="destination_tag",
            notes="tip via destination tag",
            destination_tag=tag,
        )
    if tag == BRIEFING_TAG:
        return PaymentIntent(
            amount_usd_est=BRIEFING_USD,
            method="destination_tag",
            notes="briefing unlock via destination tag",
            product_id=f"briefing-cycle-{cycle_id}",
            destination_tag=tag,
        )

    for memo in payment.get("memos") or []:
        if memo.get("type") == "revenue" and memo.get("amount_usd_est"):
            return PaymentIntent(
                amount_usd_est=float(memo["amount_usd_est"]),
                method="json_memo",
                notes=str(memo.get("notes") or "agent revenue memo"),
                product_id=memo.get("product_id"),
            )

    for text in payment.get("plain_memos") or []:
        key = text.strip().lower()
        if key in TIP_WORDS:
            return PaymentIntent(
                amount_usd_est=TIP_USD,
                method="plain_memo",
                notes=f"tip via memo '{text}'",
            )
        if key in BRIEFING_WORDS:
            return PaymentIntent(
                amount_usd_est=BRIEFING_USD,
                method="plain_memo",
                notes=f"briefing via memo '{text}'",
                product_id=f"briefing-cycle-{cycle_id}",
            )

    if FLAT_TIP_IF_BLANK and tag is None and not (payment.get("memos") or payment.get("plain_memos")):
        return PaymentIntent(
            amount_usd_est=TIP_USD,
            method="flat_tip_default",
            notes="external payment without tag/memo — factory flat tip policy",
        )

    return None


def simple_payment_instructions(cycle_id: int, treasury: str) -> Dict[str, Any]:
    """Copy-paste fields for published tip pages."""
    return {
        "treasury_address": treasury,
        "network": "xrpl_testnet",
        "easiest": {
            "step_1": f"Send XRP to {treasury}",
            "step_2": f"Set Destination Tag to {TIP_TAG}",
            "step_3": "Leave memo blank (optional)",
            "destination_tag": TIP_TAG,
            "credited_usd": TIP_USD,
        },
        "briefing_unlock": {
            "destination_tag": BRIEFING_TAG,
            "credited_usd": BRIEFING_USD,
            "product_id": f"briefing-cycle-{cycle_id}",
        },
        "alternatives": {
            "plain_memo_tip": "tip",
            "plain_memo_briefing": "briefing",
        },
    }