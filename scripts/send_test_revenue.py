"""
Send a testnet revenue payment from a secondary wallet to the factory treasury.
Verifies the full treasury_monitor → revenue_ingest pipeline on the next cycle.

Usage:
  python scripts/send_test_revenue.py --amount-usd 1.0
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv

load_dotenv()

from xrpl.wallet import Wallet

from tools.xrpl_tools import (
    create_factory_wallet,
    get_revenue_destination,
    load_factory_wallet,
    send_xrp_payment,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Send test revenue to factory treasury")
    parser.add_argument("--amount-usd", type=float, default=1.0)
    parser.add_argument("--amount-xrp", type=float, default=0.01)
    parser.add_argument("--notes", default="test supporter tip")
    parser.add_argument("--product-id", default=None, help="Optional product_id for paid briefing unlock")
    args = parser.parse_args()

    factory = load_factory_wallet(testnet=True)
    treasury = os.getenv("FACTORY_TREASURY_ADDRESS") or get_revenue_destination(factory)
    if treasury == factory.classic_address:
        raise SystemExit("Treasury must differ from factory wallet for inbound revenue.")

    supporter_seed = os.getenv("TEST_SUPPORTER_SEED")
    if supporter_seed:
        print("[TestRevenue] Using TEST_SUPPORTER_SEED from environment.")
        supporter = Wallet.from_seed(supporter_seed)
    else:
        print("[TestRevenue] Creating ephemeral supporter wallet via faucet...")
        supporter = create_factory_wallet(testnet=True, debug=False)

    memo = {
        "type": "revenue",
        "amount_usd_est": args.amount_usd,
        "notes": args.notes,
        "source": "send_test_revenue",
    }
    if args.product_id:
        memo["product_id"] = args.product_id
    print(f"[TestRevenue] Sending {args.amount_xrp} XRP from {supporter.classic_address}")
    print(f"[TestRevenue] To treasury {treasury}")
    print(f"[TestRevenue] Memo: {json.dumps(memo)}")

    result = send_xrp_payment(
        wallet=supporter,
        destination=treasury,
        amount_xrp=args.amount_xrp,
        memo_data=memo,
        verbose=True,
    )
    if not result.get("success"):
        raise SystemExit(f"Payment failed: {result}")
    print(f"[TestRevenue] Success. Run cycle_runner to ingest: {result['explorer_url']}")


if __name__ == "__main__":
    main()