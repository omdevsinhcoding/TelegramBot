"""
DreamX Coupon Bot — Payment Verification Module

Two payment gateways:

1. Paytm (from user's Python script):
   GET https://securegw.paytm.in/order/status?JsonData={"MID":"...","ORDERID":"..."}
   Response: flat JSON with STATUS, TXNAMOUNT, MID, ORDERID, TXNID, BANKTXNID

2. BharatPe (from user's upi.php):
   GET https://payments-tesseract.bharatpe.in/api/v1/merchant/transactions
       ?module=PAYMENT_QR&merchantId={mid}
   Header: token: {token}
   Response: data.transactions[] → match by bankReferenceNo (UTR)
"""

import json
import aiohttp

from bot.config import Config
from bot.utils.logger import logger

# ── Reusable aiohttp session ────────────────────────────────
_http_session: aiohttp.ClientSession | None = None


async def _get_session() -> aiohttp.ClientSession:
    """Return a reusable aiohttp session. Creates one if needed."""
    global _http_session
    if _http_session is None or _http_session.closed:
        _http_session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=15),
        )
    return _http_session


async def close_http_session():
    """Close the shared HTTP session. Call on bot shutdown."""
    global _http_session
    if _http_session and not _http_session.closed:
        await _http_session.close()
        _http_session = None


def _amounts_match(a: float, b: float) -> bool:
    """Compare payment amounts safely (avoids floating-point precision issues)."""
    return round(a, 2) == round(b, 2)


# ══════════════════════════════════════════════════════════════
# PAYTM — GET /order/status with JsonData param
# ══════════════════════════════════════════════════════════════

async def check_paytm_status(order_id: str) -> dict:
    """
    Check payment status via Paytm GET API.
    Mirrors user's Python script:
      requests.get(STATUS_API_URL, params={"JsonData": json.dumps({"MID":..,"ORDERID":..})})
    """
    from bot.database import queries as db
    ps = await db.get_payment_settings()
    mid = ps["paytm_mid"]
    payload = {"MID": mid, "ORDERID": order_id}
    json_data = json.dumps(payload)

    try:
        session = await _get_session()
        async with session.get(
            "https://securegw.paytm.in/order/status",
            params={"JsonData": json_data},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            result = await resp.json()
            logger.info(
                f"Paytm status for {order_id}: "
                f"STATUS={result.get('STATUS')}, "
                f"TXNAMOUNT={result.get('TXNAMOUNT')}"
            )
            return result
    except Exception as e:
        logger.error(f"Paytm status check failed for {order_id}: {e}")
        return {"STATUS": "API_ERROR", "error": str(e)}


def verify_paytm_response(
    response: dict, expected_amount: float, order_id: str
) -> tuple[bool, dict | None]:
    """
    Verify Paytm response — mirrors user's check_upi_status() logic:
      STATUS == "TXN_SUCCESS" and MID matches and ORDERID matches and amount matches
    """
    try:
        status = response.get("STATUS", "UNKNOWN")
        response_amount = float(response.get("TXNAMOUNT") or "0")
        mid_from_response = response.get("MID", "")
        orderid_from_response = response.get("ORDERID", "")

        if (
            status == "TXN_SUCCESS"
            and mid_from_response  # MID present
            and orderid_from_response == order_id
            and _amounts_match(response_amount, expected_amount)
        ):
            txn_id = response.get("TXNID", "N/A")
            utr = response.get("BANKTXNID", "N/A")
            logger.info(
                f"Paytm VERIFIED: order={order_id}, "
                f"amount={expected_amount}, UTR={utr}, TXNID={txn_id}"
            )
            return True, {"utr": utr, "txn_id": txn_id}

        if status == "TXN_FAILURE":
            logger.info(f"Paytm FAILED for {order_id}")
        elif status != "TXN_SUCCESS":
            logger.debug(f"Paytm PENDING for {order_id}: {status}")
        else:
            if mid_from_response:
                logger.warning(f"MID mismatch in response: got {mid_from_response}")
            if orderid_from_response != order_id:
                logger.warning(f"OrderID mismatch: expected {order_id}, got {orderid_from_response}")
            if not _amounts_match(response_amount, expected_amount):
                logger.warning(f"Amount mismatch: expected {expected_amount}, got {response_amount}")

        return False, None
    except Exception as e:
        logger.error(f"Paytm verification error: {e}")
        return False, None


def is_payment_failed(response: dict) -> bool:
    """Check if Paytm payment definitively failed.
    
    IMPORTANT: Paytm returns TXN_FAILURE for orders it doesn't know about
    (e.g. when we generate UPI QR directly). We must NOT treat "order not found"
    as a real payment failure. Only return True when user actually attempted
    payment and it was declined.
    """
    if response.get("STATUS") != "TXN_FAILURE":
        return False

    # These responses mean the order doesn't exist in Paytm yet — NOT a real failure
    resp_msg = str(response.get("RESPMSG", "")).lower()
    not_found_indicators = [
        "order not found",
        "no record found",
        "invalid order",
        "order does not exist",
        "no transaction",
    ]
    for indicator in not_found_indicators:
        if indicator in resp_msg:
            logger.debug(f"Paytm order not found (not a real failure): {resp_msg}")
            return False

    # If there's a TXNID or BANKTXNID, the user actually attempted payment and it failed
    if response.get("TXNID") or response.get("BANKTXNID"):
        logger.info(f"Paytm payment genuinely failed: {resp_msg}")
        return True

    # For other TXN_FAILURE cases without transaction IDs, be conservative — don't mark as failed
    logger.debug(f"Paytm TXN_FAILURE but no txn IDs, treating as pending: {resp_msg}")
    return False


# ══════════════════════════════════════════════════════════════
# BHARATPE — GET /merchant/transactions, match by UTR
# Mirrors user's upi.php logic exactly
# ══════════════════════════════════════════════════════════════

async def fetch_bharatpe_transactions() -> list:
    """
    Fetch recent BharatPe transactions.
    Uses dynamic payment settings from DB with .env fallback.
    """
    from bot.database import queries as db
    ps = await db.get_payment_settings()
    mid = ps["bharatpe_merchant_id"]
    token = ps["bharatpe_token"]

    if not mid or not token:
        logger.debug("BharatPe not configured, skipping.")
        return []

    url = (
        f"https://payments-tesseract.bharatpe.in/api/v1/merchant/transactions"
        f"?module=PAYMENT_QR&merchantId={mid}"
    )

    try:
        session = await _get_session()
        async with session.get(
            url,
            headers={"token": token},
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            result = await resp.json()
            transactions = result.get("data", {}).get("transactions", [])
            logger.info(f"BharatPe fetched {len(transactions)} transactions")
            return transactions
    except Exception as e:
        logger.error(f"BharatPe fetch failed: {e}")
        return []


async def verify_bharatpe_utr(utr: str, expected_amount: float = 0) -> tuple[bool, dict | None]:
    """
    Verify payment by matching UTR against BharatPe transactions.
    Mirrors user's upi.php logic exactly:
      foreach($transactions as $transaction) {
          if($transaction->bankReferenceNo == $txn_id) {
              $amount = $transaction->amount;
              // credit balance
          }
      }

    The PHP code does NOT do strict amount matching — it accepts the
    payment if the UTR is found in BharatPe API, and uses the amount
    from the API as the actual paid amount.

    expected_amount is now optional and only used for informational
    logging, NOT for rejection.  The caller is responsible for any
    minimum-amount checks.
    """
    transactions = await fetch_bharatpe_transactions()

    for txn in transactions:
        bank_ref = str(txn.get("bankReferenceNo", ""))

        if bank_ref == utr:
            amount = float(txn.get("amount", 0))
            payer_name = txn.get("payerName", "N/A")
            payer_handle = txn.get("payerHandle", "N/A")

            if expected_amount and not _amounts_match(amount, expected_amount):
                logger.info(
                    f"BharatPe UTR {utr}: paid {amount}, expected {expected_amount} "
                    f"(accepting — amount check is caller's job)"
                )

            logger.info(
                f"BharatPe VERIFIED: UTR={utr}, amount={amount}, "
                f"payer={payer_name} ({payer_handle})"
            )

            return True, {
                "utr": utr,
                "txn_id": bank_ref,
                "amount": amount,
                "payer_name": payer_name,
                "payer_handle": payer_handle,
            }

    logger.debug(f"BharatPe UTR {utr} not found in {len(transactions)} BharatPe transactions")
    return False, None


# ══════════════════════════════════════════════════════════════
# UNIFIED INTERFACE
# ══════════════════════════════════════════════════════════════

async def check_upi_status(order_id: str, gateway: str = "paytm") -> dict:
    """Unified payment status check. For Paytm only (BharatPe uses UTR matching)."""
    return await check_paytm_status(order_id)


def verify_payment(
    response: dict, expected_amount: float, order_id: str,
    gateway: str = "paytm",
) -> tuple[bool, dict | None]:
    """Unified Paytm payment verification."""
    return verify_paytm_response(response, expected_amount, order_id)
