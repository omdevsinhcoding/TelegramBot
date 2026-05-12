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


# ══════════════════════════════════════════════════════════════
# PAYTM — GET /order/status with JsonData param
# ══════════════════════════════════════════════════════════════

async def check_paytm_status(order_id: str) -> dict:
    """
    Check payment status via Paytm GET API.
    Mirrors user's Python script:
      requests.get(STATUS_API_URL, params={"JsonData": json.dumps({"MID":..,"ORDERID":..})})
    """
    payload = {"MID": Config.PAYTM_MID, "ORDERID": order_id}
    json_data = json.dumps(payload)

    try:
        async with aiohttp.ClientSession() as session:
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
        response_amount = float(response.get("TXNAMOUNT", "0"))
        mid_from_response = response.get("MID", "")
        orderid_from_response = response.get("ORDERID", "")

        if (
            status == "TXN_SUCCESS"
            and mid_from_response == Config.PAYTM_MID
            and orderid_from_response == order_id
            and response_amount == expected_amount
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
            if mid_from_response != Config.PAYTM_MID:
                logger.warning(f"MID mismatch: expected {Config.PAYTM_MID}, got {mid_from_response}")
            if orderid_from_response != order_id:
                logger.warning(f"OrderID mismatch: expected {order_id}, got {orderid_from_response}")
            if response_amount != expected_amount:
                logger.warning(f"Amount mismatch: expected {expected_amount}, got {response_amount}")

        return False, None
    except Exception as e:
        logger.error(f"Paytm verification error: {e}")
        return False, None


def is_payment_failed(response: dict) -> bool:
    """Check if Paytm payment definitively failed."""
    return response.get("STATUS") == "TXN_FAILURE"


# ══════════════════════════════════════════════════════════════
# BHARATPE — GET /merchant/transactions, match by UTR
# Mirrors user's upi.php logic exactly
# ══════════════════════════════════════════════════════════════

async def fetch_bharatpe_transactions() -> list:
    """
    Fetch recent BharatPe transactions.
    Mirrors:
      $url = "https://payments-tesseract.bharatpe.in/api/v1/merchant/transactions
              ?module=PAYMENT_QR&merchantId={$upi_merchant}";
      curl_setopt($ch, CURLOPT_HTTPHEADER, ["token: $upi_token"]);
    """
    mid = Config.BHARATPE_MERCHANT_ID
    token = Config.BHARATPE_TOKEN

    if not mid or not token:
        logger.debug("BharatPe not configured, skipping.")
        return []

    url = (
        f"https://payments-tesseract.bharatpe.in/api/v1/merchant/transactions"
        f"?module=PAYMENT_QR&merchantId={mid}"
    )

    try:
        async with aiohttp.ClientSession() as session:
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


async def verify_bharatpe_utr(utr: str, expected_amount: float) -> tuple[bool, dict | None]:
    """
    Verify payment by matching UTR against BharatPe transactions.
    Mirrors user's upi.php logic:
      foreach($transactions as $transaction) {
          if($transaction->bankReferenceNo == $txn_id) {
              $amount = $transaction->amount;
              // verify amount >= min, credit balance
          }
      }
    """
    transactions = await fetch_bharatpe_transactions()

    for txn in transactions:
        bank_ref = str(txn.get("bankReferenceNo", ""))

        if bank_ref == utr:
            amount = float(txn.get("amount", 0))

            if amount != expected_amount:
                logger.warning(
                    f"BharatPe UTR {utr}: amount mismatch "
                    f"(expected {expected_amount}, got {amount})"
                )
                return False, None

            payer_name = txn.get("payerName", "N/A")
            payer_handle = txn.get("payerHandle", "N/A")

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

    logger.debug(f"BharatPe UTR {utr} not found in transactions")
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
