"""
XRPL Tools for RSI-EAF
Grounds all economic activity on the XRP Ledger for transparency, observability, and real auditability.

Uses official xrpl-py. Start on Testnet. All significant economic events should produce (or reference)
an XRPL Payment transaction with structured Memo metadata.

Never commit seeds. Use environment variables or secure vault.
"""

import os
import json
import threading
import time
from typing import Optional, Dict, Any, Callable
from decimal import Decimal

from dotenv import load_dotenv
load_dotenv()   # Load .env file so FACTORY_XRPL_SEED etc. are available

from xrpl.clients import JsonRpcClient, WebsocketClient
from xrpl.wallet import Wallet, generate_faucet_wallet
from xrpl.models.requests import Subscribe
from xrpl.models.requests.subscribe import StreamParameter
from xrpl.models.transactions import Payment, Memo
from xrpl.transaction import submit_and_wait
from xrpl.utils import xrp_to_drops, drops_to_xrp
from xrpl.account import get_balance
from xrpl.ledger import get_latest_validated_ledger_sequence

# Default Testnet
XRPL_TESTNET_URL = os.getenv("XRPL_TESTNET_URL", "https://s.altnet.rippletest.net:51234")
XRPL_TESTNET_WS_URL = os.getenv(
    "XRPL_TESTNET_WS_URL", "wss://s.altnet.rippletest.net:51233"
)
XRPL_MAINNET_URL = os.getenv("XRPL_MAINNET_URL", "https://xrplcluster.com/")  # or reliable public node
XRPL_MAINNET_WS_URL = os.getenv("XRPL_MAINNET_WS_URL", "wss://xrplcluster.com/")

# Factory XRPL account (set via .env; never hardcode)
FACTORY_XRPL_SEED = os.getenv("FACTORY_XRPL_SEED")  # e.g. sEd... or hex
FACTORY_XRPL_ADDRESS = os.getenv("FACTORY_XRPL_ADDRESS")  # classic address for quick reference
XRPL_WS_QUIET = os.getenv("XRPL_WS_QUIET", "true").lower() in {"1", "true", "yes"}


def _xrpl_log(message: str, *, force: bool = False) -> None:
    if force or not XRPL_WS_QUIET:
        print(message)


def get_client(testnet: bool = True) -> JsonRpcClient:
    """Return a JSON-RPC client for Testnet or Mainnet."""
    url = XRPL_TESTNET_URL if testnet else XRPL_MAINNET_URL
    return JsonRpcClient(url)


def create_factory_wallet(testnet: bool = True, debug: bool = True) -> Wallet:
    """
    Create a new factory-controlled XRPL wallet.
    On testnet, attempts to use the public faucet to fund it automatically.
    If the faucet returns 429 (rate limited — very common), it prints clear
    manual instructions instead of crashing.
    Returns the Wallet object. Store the seed securely (e.g. in .env).
    """
    client = get_client(testnet)
    if testnet:
        try:
            wallet = generate_faucet_wallet(client, debug=debug)
            print(f"[XRPL] New testnet wallet created & funded via faucet: {wallet.classic_address}")
            print(f"[XRPL] Seed (STORE SECURELY in .env as FACTORY_XRPL_SEED): {wallet.seed}")
            return wallet
        except Exception as e:
            # Handle rate limiting (429) and other faucet issues gracefully
            if "429" in str(e) or "Too Many Requests" in str(e):
                print("\n[XRPL] ERROR: Public testnet faucet is currently rate-limited (HTTP 429).")
                print("This is very common right now due to high usage from AI/agent experiments.")
                print("\nMANUAL WORKAROUND (takes 30 seconds):")
                print("1. Go to: https://testnet.xrpl.org/ or search 'XRPL testnet faucet'")
                print("2. Generate a new wallet locally (or use the one printed below if partial)")
                print("3. Copy the classic address and paste it into the web faucet to receive ~10,000 test XRP")
                print("4. Once funded, set these in your .env file:")
                print("   FACTORY_XRPL_SEED=sEdYourSecretSeedHere")
                print("   FACTORY_XRPL_ADDRESS=rYourClassicAddressHere")
                print("\nThen re-run this script. The code will load from .env instead of hitting the faucet.")
                print("You can also try again in a few minutes — the faucet usually recovers quickly.\n")
            raise RuntimeError(
                "Failed to auto-fund testnet wallet via faucet (rate limited or temporary issue). "
                "Please use the manual workaround above and set FACTORY_XRPL_SEED in .env."
            ) from e
    else:
        # For mainnet: user must provide seed via env or secure input
        if not FACTORY_XRPL_SEED:
            raise ValueError("FACTORY_XRPL_SEED env var required for mainnet wallet creation")
        wallet = Wallet.from_seed(FACTORY_XRPL_SEED)
        print(f"[XRPL] Loaded mainnet wallet: {wallet.classic_address}")
        return wallet


def get_revenue_destination(wallet: Wallet) -> str:
    """
    Resolve payment destination for revenue anchoring.
    XRPL disallows self-payments, so destination must differ from sender.
    """
    treasury = os.getenv("FACTORY_TREASURY_ADDRESS")
    if treasury and treasury != wallet.classic_address:
        return treasury
    if FACTORY_XRPL_ADDRESS and FACTORY_XRPL_ADDRESS != wallet.classic_address:
        return FACTORY_XRPL_ADDRESS
    raise ValueError(
        "FACTORY_TREASURY_ADDRESS (or a distinct FACTORY_XRPL_ADDRESS) is required. "
        "XRPL does not allow payments where sender equals destination."
    )


def load_factory_wallet(testnet: bool = True) -> Wallet:
    """Load existing factory wallet from seed in env. Falls back to creating on testnet."""
    if FACTORY_XRPL_SEED:
        return Wallet.from_seed(FACTORY_XRPL_SEED)
    if testnet:
        print("[XRPL] No seed found. Creating new testnet wallet via faucet...")
        return create_factory_wallet(testnet=True)
    raise ValueError("FACTORY_XRPL_SEED required for mainnet. Set it in .env")


def send_xrp_payment(
    wallet: Wallet,
    destination: str,
    amount_xrp: float | str | Decimal,
    memo_data: Optional[Dict[str, Any]] = None,
    memo_type: str = "rsi_eaf_economic_event",
    destination_tag: Optional[int] = None,
    testnet: bool = True,
    verbose: bool = True,
) -> Dict[str, Any]:
    """
    Send XRP payment with optional structured Memo (JSON metadata hex-encoded).
    This is the primary way to ground economic events on-ledger.

    memo_data example:
    {
        "cycle": 7,
        "source": "content_engine",
        "type": "ad_revenue",
        "amount_usd_est": 1.23,
        "notes": "niche: ai-tools-for-devs"
    }
    """
    client = get_client(testnet)
    if isinstance(amount_xrp, str):
        amount_xrp = Decimal(amount_xrp)
    amount_drops = xrp_to_drops(amount_xrp)

    memos = []
    if memo_data:
        memo_json = json.dumps(memo_data, separators=(",", ":"))
        # XRPL Memos are hex-encoded
        memo_hex = memo_json.encode("utf-8").hex().upper()
        memos.append(
            Memo(
                memo_type=memo_type.encode("utf-8").hex().upper(),
                memo_data=memo_hex,
            )
        )

    payment_kwargs: Dict[str, Any] = {
        "account": wallet.classic_address,
        "destination": destination,
        "amount": amount_drops,
        "memos": memos if memos else None,
    }
    if destination_tag is not None:
        payment_kwargs["destination_tag"] = int(destination_tag)
    payment = Payment(**payment_kwargs)

    if verbose:
        print(f"[XRPL] Preparing Payment: {amount_xrp} XRP to {destination}")
        if memo_data:
            print(f"[XRPL] Memo: {memo_data}")

    response = submit_and_wait(payment, client, wallet)
    tx_hash = response.result.get("hash")
    validated_ledger = response.result.get("validated_ledger_index")

    result = {
        "success": response.is_successful(),
        "tx_hash": tx_hash,
        "ledger_index": validated_ledger,
        "explorer_url": f"https://{'testnet.' if testnet else ''}xrpl.org/transactions/{tx_hash}",
        "memo_data": memo_data,
        "raw_response": response.result if verbose else None,
    }

    if verbose:
        print(f"[XRPL] Payment {'SUCCESS' if result['success'] else 'FAILED'}: {tx_hash}")
        print(f"[XRPL] Explorer: {result['explorer_url']}")

    return result


def get_account_xrp_balance(address: str, testnet: bool = True) -> Decimal:
    """Return current XRP balance for an address as Decimal (in XRP, not drops)."""
    client = get_client(testnet)
    balance_drops = get_balance(address, client)
    # xrpl-py get_balance() can return int in newer versions; drops_to_xrp requires string
    return drops_to_xrp(str(balance_drops))


def parse_ws_payment_message(
    msg: Dict[str, Any],
    watch_address: str,
    testnet: bool = True,
) -> Optional[Dict[str, Any]]:
    """
    Extract inbound Payment fields from an XRPL WebSocket transaction message.
    Handles both legacy ``transaction`` and newer ``tx_json`` payload shapes.
    """
    if msg.get("type") != "transaction":
        return None

    engine_result = msg.get("engine_result") or msg.get("meta", {}).get("TransactionResult")
    if engine_result and engine_result != "tesSUCCESS":
        return None
    if msg.get("validated") is False:
        return None

    tx = msg.get("transaction") or msg.get("tx_json") or {}
    if tx.get("TransactionType") != "Payment":
        return None
    if tx.get("Destination") != watch_address:
        return None

    tx_hash = (
        msg.get("tx_hash")
        or tx.get("hash")
        or msg.get("hash")
    )
    return {
        "tx_hash": tx_hash,
        "from": tx.get("Account"),
        "amount_drops": tx.get("Amount"),
        "memo": tx.get("Memos"),
        "ledger_index": msg.get("ledger_index") or tx.get("ledger_index"),
        "timestamp": time.time(),
        "explorer_url": (
            f"https://{'testnet.' if testnet else ''}xrpl.org/transactions/{tx_hash}"
            if tx_hash else None
        ),
    }


def monitor_incoming_payments(
    address: str,
    callback: Callable[[Dict[str, Any]], None],
    testnet: bool = True,
    timeout_seconds: Optional[int] = None,
) -> int:
    """
    Real-time WebSocket monitor for incoming Payments to a specific address.
    Calls callback(dict) for each relevant transaction.
    Returns count of payments observed during the poll window (hard wall-clock cap).
    """
    url = XRPL_TESTNET_WS_URL if testnet else XRPL_MAINNET_WS_URL
    poll_timeout = float(timeout_seconds or 3)
    _xrpl_log(f"[XRPL] Starting WebSocket monitor for incoming payments to {address}...")

    state: Dict[str, Any] = {"observed": 0}

    def _poll_loop() -> None:
        try:
            with WebsocketClient(url, timeout=min(poll_timeout, 10.0)) as ws:
                ws.send(
                    Subscribe(
                        accounts=[address],
                        streams=[StreamParameter.TRANSACTIONS],
                    )
                )
                _xrpl_log(f"[XRPL] Subscribed to transactions (poll {poll_timeout:.0f}s).")
                deadline = time.monotonic() + poll_timeout
                for msg in ws:
                    if time.monotonic() >= deadline:
                        break
                    payment = parse_ws_payment_message(msg, address, testnet=testnet)
                    if not payment:
                        continue
                    callback(payment)
                    state["observed"] += 1
            if state["observed"]:
                _xrpl_log(
                    f"[XRPL] Monitor poll complete ({state['observed']} payment(s) observed).",
                    force=True,
                )
        except Exception as exc:
            _xrpl_log(f"[XRPL] Monitor error: {exc}", force=True)
            state["error"] = str(exc)

    worker = threading.Thread(target=_poll_loop, name="xrpl-ws-poll", daemon=True)
    worker.start()
    worker.join(timeout=poll_timeout + 3.0)
    if worker.is_alive():
        _xrpl_log(
            f"[XRPL] Monitor hard-timeout after {poll_timeout:.0f}s — continuing cycle",
            force=True,
        )
    return int(state["observed"])


def query_recent_transactions(
    address: str,
    limit: int = 10,
    testnet: bool = True,
    retries: int = 3,
) -> list:
    """Fetch recent transactions with retries on transient network errors."""
    from xrpl.models.requests import AccountTx

    last_exc: Optional[Exception] = None
    for attempt in range(retries):
        try:
            client = get_client(testnet)
            req = AccountTx(account=address, limit=limit)
            response = client.request(req)
            return response.result.get("transactions", [])
        except Exception as exc:
            last_exc = exc
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
    raise last_exc  # type: ignore[misc]


# Convenience: Quick self-test helper
if __name__ == "__main__":
    print("=== RSI-EAF XRPL Tools Self-Test ===")
    w = load_factory_wallet(testnet=True)
    print(f"Factory Address: {w.classic_address}")
    bal = get_account_xrp_balance(w.classic_address)
    print(f"Current Balance: {bal} XRP")

    # Example: Send small self-payment with metadata (for testing only)
    # result = send_xrp_payment(
    #     wallet=w,
    #     destination=w.classic_address,
    #     amount_xrp=0.01,
    #     memo_data={"cycle": 0, "source": "bootstrap_test", "type": "self_test", "note": "XRPL grounding validated"}
    # )
    # print("Test tx:", result.get("explorer_url"))
