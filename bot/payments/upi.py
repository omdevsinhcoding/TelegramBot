"""
DreamX Coupon Bot — UPI Payment Module
Generates UPI intent URLs and QR codes.

Mirrors the user's existing logic from get.php and pay.py:
  UPI URL format: upi://pay?pa={vpa}&pn={payee}&paytmqr={qr_id}&tr={txn_ref}&tn={note}&am={amount}
  QR generation: branded PNG with payment details
"""

import io
import time
import random
import string
import qrcode
from PIL import Image, ImageDraw, ImageFont
from bot.config import Config
from bot.utils.logger import logger


def generate_unique_txn_id() -> str:
    """
    Generate unique ORDERID/txn_ref_id.
    Mirrors: TXN_{timestamp}_{random_8_chars}
    This is the transaction reference used as ORDERID for Paytm status checks.
    """
    timestamp = int(time.time())
    random_str = "".join(random.choices(string.ascii_letters + string.digits, k=8))
    return f"TXN_{timestamp}_{random_str}"


def generate_upi_intent_url(
    amount: float,
    txn_ref_id: str,
    note: str = "Coupon Purchase",
    gateway: str = "paytm",
) -> str:
    """
    Generate UPI deep-link URL for payment.
    
    gateway='paytm'   → uses Paytm UPI ID + paytmqr param
    gateway='bharatpe' → uses BharatPe UPI ID (no paytmqr)
    """
    payee = Config.UPI_PAYEE_NAME

    if gateway == "bharatpe" and Config.BHARATPE_UPI_ID:
        vpa = Config.BHARATPE_UPI_ID
        url = (
            f"upi://pay?pa={vpa}"
            f"&pn={payee}"
            f"&tr={txn_ref_id}"
            f"&tn={note}"
            f"&am={amount:.2f}"
            f"&cu=INR"
        )
    else:
        # Paytm gateway
        vpa = Config.PAYTM_UPI_ID
        paytmqr = Config.PAYTM_QR_CODE
        url = (
            f"upi://pay?pa={vpa}"
            f"&pn={payee}"
        )
        if paytmqr:
            url += f"&paytmqr={paytmqr}"
        url += (
            f"&tr={txn_ref_id}"
            f"&tn={note}"
            f"&am={amount:.2f}"
            f"&cu=INR"
        )

    logger.info(f"Generated UPI URL [{gateway}]: txn={txn_ref_id}, amount={amount:.2f}")
    return url


def create_qr_buffer(upi_url: str, amount: float, txn_ref: str) -> io.BytesIO:
    """
    Generate a branded QR code image and return as bytes buffer.
    Creates a professional dark-themed QR with payment details.
    """
    # Create QR code
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=4,
    )
    qr.add_data(upi_url)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="#1a1a2e", back_color="#ffffff").convert("RGB")

    # Create branded canvas
    qr_w, qr_h = qr_img.size
    padding = 60
    canvas_w = qr_w + padding * 2
    canvas_h = qr_h + padding * 2 + 120

    canvas = Image.new("RGB", (canvas_w, canvas_h), "#0f0f23")
    draw = ImageDraw.Draw(canvas)

    # Load fonts (fallback to default if system font unavailable)
    try:
        font_title = ImageFont.truetype("arial.ttf", 24)
        font_info = ImageFont.truetype("arial.ttf", 18)
    except OSError:
        font_title = ImageFont.load_default()
        font_info = ImageFont.load_default()

    # Header
    draw.text(
        (canvas_w // 2, 25), "💎 DreamX Store",
        fill="#e94560", anchor="mt", font=font_title,
    )

    # Paste QR
    canvas.paste(qr_img, (padding, padding + 40))

    # Footer info
    y_footer = padding + 40 + qr_h + 15
    draw.text(
        (canvas_w // 2, y_footer), f"Amount: ₹{amount:.2f}",
        fill="#ffffff", anchor="mt", font=font_info,
    )
    draw.text(
        (canvas_w // 2, y_footer + 30), f"Ref: {txn_ref}",
        fill="#a0a0a0", anchor="mt", font=font_info,
    )
    draw.text(
        (canvas_w // 2, y_footer + 55), "Scan with any UPI app",
        fill="#16c784", anchor="mt", font=font_info,
    )

    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
    buf.seek(0)
    return buf
