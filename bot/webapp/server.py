"""
DreamX Coupon Bot — Analytics Web Server
Serves the admin analytics dashboard as a Telegram Mini App.

Uses aiohttp to run a lightweight HTTP server alongside the bot.
Admin verification is done via Telegram user_id checked against
the admin list (Config.ADMIN_IDS + DB admins).
"""

import json
import hashlib
import hmac
from urllib.parse import parse_qs
from pathlib import Path
from datetime import datetime

from aiohttp import web
from bot.config import Config
from bot.database import queries as db
from bot.utils.logger import logger


# ── Static file path ──────────────────────────────────────
STATIC_DIR = Path(__file__).parent / "static"


def validate_init_data(init_data: str, bot_token: str) -> dict | None:
    """Validate Telegram WebApp initData and return parsed user data.
    
    Uses HMAC-SHA256 to verify the data came from Telegram.
    Returns the parsed data dict if valid, None if invalid.
    """
    try:
        parsed = parse_qs(init_data, keep_blank_values=True)
        
        # Extract the hash
        received_hash = parsed.get("hash", [""])[0]
        if not received_hash:
            return None
        
        # Build data-check-string (all params sorted alphabetically, excluding hash)
        data_pairs = []
        for key, values in sorted(parsed.items()):
            if key == "hash":
                continue
            data_pairs.append(f"{key}={values[0]}")
        data_check_string = "\n".join(data_pairs)
        
        # Compute HMAC
        secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        
        if computed_hash != received_hash:
            return None
        
        # Parse user data
        user_str = parsed.get("user", [""])[0]
        if user_str:
            return json.loads(user_str)
        return None
    except Exception as e:
        logger.warning(f"[WEBAPP] initData validation error: {e}")
        return None


def _serialize(obj):
    """JSON serializer for datetime and Decimal objects."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if hasattr(obj, '__float__'):
        return float(obj)
    return str(obj)


# ── API Routes ────────────────────────────────────────────

async def handle_index(request: web.Request) -> web.Response:
    """Serve the analytics dashboard HTML."""
    html_path = STATIC_DIR / "analytics.html"
    if not html_path.exists():
        return web.Response(text="Dashboard not found", status=404)
    return web.FileResponse(html_path)


async def handle_verify(request: web.Request) -> web.Response:
    """Verify admin identity from Telegram initData."""
    try:
        body = await request.json()
        init_data = body.get("initData", "")
        user_id = body.get("user_id")
        
        # Try Telegram initData validation first
        user = validate_init_data(init_data, Config.BOT_TOKEN) if init_data else None
        
        if user:
            user_id = user.get("id")
        
        if not user_id:
            return web.json_response({
                "verified": False,
                "error": "No user identity found"
            })
        
        user_id = int(user_id)
        is_admin = Config.is_admin(user_id)
        
        if not is_admin:
            return web.json_response({
                "verified": False,
                "error": "not_admin",
                "user_id": user_id
            })
        
        return web.json_response({
            "verified": True,
            "user_id": user_id,
            "name": user.get("first_name", "") if user else str(user_id)
        })
    except Exception as e:
        logger.error(f"[WEBAPP] Verify error: {e}")
        return web.json_response({"verified": False, "error": str(e)}, status=500)


async def handle_analytics(request: web.Request) -> web.Response:
    """Return full analytics data (admin-only)."""
    try:
        # Get user_id from query params
        user_id = request.query.get("user_id")
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)
        
        user_id = int(user_id)
        if not Config.is_admin(user_id):
            return web.json_response({"error": "Unauthorized"}, status=401)
        
        # Fetch all analytics data
        sales_stats = await db.get_sales_stats()
        admin_analytics = await db.get_admin_sales_analytics()
        product_analytics = await db.get_product_analytics()
        recent_sales = await db.get_recent_sales(100)
        daily_revenue = await db.get_daily_revenue(30)
        user_count = await db.get_user_count()
        
        # Get admin names
        all_admins = await db.get_all_admins()
        admin_names = {}
        for a in all_admins:
            admin_names[a["telegram_id"]] = str(a["telegram_id"])
        # Also include seed admins
        for aid in Config.ADMIN_IDS:
            if aid not in admin_names:
                admin_names[aid] = str(aid)
        
        # Try to get admin names from users table
        pool = await db.get_pool()
        for aid in list(admin_names.keys()):
            user = await pool.fetchrow(
                "SELECT full_name, username FROM users WHERE telegram_id = $1", aid
            )
            if user:
                name = user["full_name"] or user["username"] or str(aid)
                admin_names[aid] = name
        
        # Build response
        data = {
            "summary": {
                "total_users": user_count,
                "total_orders": sales_stats["total_orders"],
                "total_paid": sales_stats["total_paid"],
                "total_pending": sales_stats["total_pending"],
                "total_expired": sales_stats["total_expired"],
                "total_revenue": float(sales_stats["total_revenue"]),
            },
            "admin_sales": [
                {
                    "admin_id": r["admin_id"],
                    "admin_name": admin_names.get(r["admin_id"], str(r["admin_id"])),
                    "products_added": r["products_added"],
                    "total_sold": r["total_sold"],
                    "total_revenue": float(r["total_revenue"]),
                    "pending_orders": r["pending_orders"],
                    "pending_revenue": float(r["pending_revenue"]),
                }
                for r in admin_analytics
            ],
            "products": [
                {
                    "coupon_id": r["coupon_id"],
                    "title": r["title"],
                    "price": float(r["price"]),
                    "stock": r["stock"],
                    "is_active": r["is_active"],
                    "admin_id": r["admin_id"],
                    "admin_name": admin_names.get(r["admin_id"], "Unknown") if r["admin_id"] else "Unknown",
                    "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                    "sold_count": r["sold_count"],
                    "revenue": float(r["revenue"]),
                    "pending_count": r["pending_count"],
                    "codes_sold": r["codes_sold"],
                    "codes_available": r["codes_available"],
                }
                for r in product_analytics
            ],
            "recent_sales": [
                {
                    "order_id": r["order_id"],
                    "user_id": r["user_id"],
                    "amount": float(r["amount"]),
                    "quantity": r["quantity"],
                    "status": r["status"],
                    "paid_at": r["paid_at"].isoformat() if r["paid_at"] else None,
                    "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                    "coupon_title": r["coupon_title"],
                    "admin_id": r["admin_id"],
                    "admin_name": admin_names.get(r["admin_id"], "Unknown") if r["admin_id"] else "Unknown",
                    "buyer_name": r["buyer_name"] or "Unknown",
                }
                for r in recent_sales
            ],
            "daily_revenue": [
                {
                    "day": r["day"].isoformat() if r["day"] else None,
                    "order_count": r["order_count"],
                    "revenue": float(r["revenue"]),
                }
                for r in daily_revenue
            ],
            "admin_names": {str(k): v for k, v in admin_names.items()},
        }
        
        return web.json_response(data, dumps=lambda x: json.dumps(x, default=_serialize))
    except Exception as e:
        logger.error(f"[WEBAPP] Analytics error: {e}", exc_info=True)
        return web.json_response({"error": str(e)}, status=500)


async def handle_static(request: web.Request) -> web.Response:
    """Serve static files (CSS, JS)."""
    filename = request.match_info.get("filename", "")
    filepath = STATIC_DIR / filename
    if not filepath.exists() or not filepath.is_file():
        return web.Response(text="Not found", status=404)
    return web.FileResponse(filepath)


def create_webapp() -> web.Application:
    """Create the aiohttp web application."""
    app = web.Application()
    
    # Routes
    app.router.add_get("/", handle_index)
    app.router.add_post("/api/verify", handle_verify)
    app.router.add_get("/api/analytics", handle_analytics)
    app.router.add_get("/static/{filename}", handle_static)
    
    return app


async def start_webapp(port: int = 8443):
    """Start the web server on the given port."""
    app = create_webapp()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"[WEBAPP] Analytics web server started on port {port}")
    return runner
