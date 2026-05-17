#!/usr/bin/env python3
"""
DreamX Analytics — Standalone Web Server
=========================================
This runs INDEPENDENTLY from the bot. Deploy it on any server with HTTPS.
Connects directly to the same NeonDB PostgreSQL database.

Usage:
    python webapp_standalone.py

Environment variables required:
    DATABASE_URL  — Same PostgreSQL connection string as the bot
    ADMIN_IDS     — Comma-separated Telegram admin IDs (same as bot)
    BOT_TOKEN     — Bot token (for initData validation)
    PORT          — Port to listen on (default: 8443)
"""

import os
import sys
import json
import hashlib
import hmac
import asyncio
from urllib.parse import parse_qs
from pathlib import Path
from datetime import datetime

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

import asyncpg
from aiohttp import web

# ── Config ────────────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
PORT = int(os.getenv("PORT", os.getenv("WEBAPP_PORT", "8443")))

STATIC_DIR = Path(__file__).parent / "bot" / "webapp" / "static"
if not STATIC_DIR.exists():
    STATIC_DIR = Path(__file__).parent / "static"
    if not STATIC_DIR.exists():
        STATIC_DIR = Path(__file__).parent

# ── Database ──────────────────────────────────────────────
_pool = None

async def get_pool():
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(dsn=DATABASE_URL, min_size=1, max_size=5, command_timeout=30)
    return _pool


async def get_db_admin_ids() -> set:
    pool = await get_pool()
    rows = await pool.fetch("SELECT telegram_id FROM admins")
    return {row["telegram_id"] for row in rows}


def is_admin(user_id: int, db_admins: set = None) -> bool:
    if user_id in ADMIN_IDS:
        return True
    if db_admins and user_id in db_admins:
        return True
    return False


# ── Telegram initData validation ──────────────────────────
def validate_init_data(init_data: str) -> dict | None:
    try:
        parsed = parse_qs(init_data, keep_blank_values=True)
        received_hash = parsed.get("hash", [""])[0]
        if not received_hash:
            return None
        data_pairs = []
        for key, values in sorted(parsed.items()):
            if key == "hash":
                continue
            data_pairs.append(f"{key}={values[0]}")
        data_check_string = "\n".join(data_pairs)
        secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        if computed_hash != received_hash:
            return None
        user_str = parsed.get("user", [""])[0]
        if user_str:
            return json.loads(user_str)
        return None
    except Exception:
        return None


# ── API Handlers ──────────────────────────────────────────

async def handle_index(request):
    html_path = STATIC_DIR / "analytics.html"
    if not html_path.exists():
        return web.Response(text="Analytics dashboard not found. Check STATIC_DIR.", status=404)
    return web.FileResponse(html_path)


async def handle_verify(request):
    try:
        body = await request.json()
        init_data = body.get("initData", "")
        user_id = body.get("user_id")

        user = validate_init_data(init_data) if init_data else None
        if user:
            user_id = user.get("id")

        if not user_id:
            return web.json_response({"verified": False, "error": "No user identity"})

        user_id = int(user_id)
        db_admins = set()
        try:
            db_admins = await get_db_admin_ids()
        except Exception:
            pass

        if not is_admin(user_id, db_admins):
            return web.json_response({"verified": False, "error": "not_admin", "user_id": user_id})

        return web.json_response({
            "verified": True,
            "user_id": user_id,
            "name": user.get("first_name", str(user_id)) if user else str(user_id)
        })
    except Exception as e:
        return web.json_response({"verified": False, "error": str(e)}, status=500)


async def handle_analytics(request):
    try:
        user_id = request.query.get("user_id")
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)

        user_id = int(user_id)
        db_admins = set()
        try:
            db_admins = await get_db_admin_ids()
        except Exception:
            pass

        if not is_admin(user_id, db_admins):
            return web.json_response({"error": "Unauthorized"}, status=401)

        pool = await get_pool()

        # Summary stats
        sales = await pool.fetchrow("""
            SELECT
                COUNT(*) FILTER (WHERE status = 'paid') as total_paid,
                COUNT(*) FILTER (WHERE status = 'pending') as total_pending,
                COUNT(*) FILTER (WHERE status = 'expired') as total_expired,
                COALESCE(SUM(amount) FILTER (WHERE status = 'paid'), 0) as total_revenue,
                COUNT(*) as total_orders
            FROM orders
        """)
        user_count = await pool.fetchval("SELECT COUNT(*) FROM users") or 0

        # Per-admin sales
        admin_rows = await pool.fetch("""
            SELECT c.created_by AS admin_id,
                COUNT(DISTINCT c.id) AS products_added,
                COUNT(o.order_id) FILTER (WHERE o.status IN ('paid','delivered')) AS total_sold,
                COALESCE(SUM(o.amount) FILTER (WHERE o.status IN ('paid','delivered')), 0) AS total_revenue,
                COUNT(o.order_id) FILTER (WHERE o.status = 'pending') AS pending_orders,
                COALESCE(SUM(o.amount) FILTER (WHERE o.status = 'pending'), 0) AS pending_revenue
            FROM coupons c LEFT JOIN orders o ON o.coupon_id = c.id
            WHERE c.created_by IS NOT NULL
            GROUP BY c.created_by ORDER BY total_revenue DESC
        """)

        # Products
        product_rows = await pool.fetch("""
            SELECT c.id AS coupon_id, c.title, c.discounted_price AS price, c.stock,
                c.is_active, c.created_by AS admin_id, c.created_at,
                COUNT(o.order_id) FILTER (WHERE o.status IN ('paid','delivered')) AS sold_count,
                COALESCE(SUM(o.amount) FILTER (WHERE o.status IN ('paid','delivered')), 0) AS revenue,
                COUNT(o.order_id) FILTER (WHERE o.status = 'pending') AS pending_count,
                (SELECT COUNT(*) FROM coupon_codes cc WHERE cc.coupon_id = c.id AND cc.is_sold = TRUE) AS codes_sold,
                (SELECT COUNT(*) FROM coupon_codes cc WHERE cc.coupon_id = c.id AND cc.is_sold = FALSE) AS codes_available
            FROM coupons c LEFT JOIN orders o ON o.coupon_id = c.id
            GROUP BY c.id ORDER BY revenue DESC
        """)

        # Recent sales
        recent = await pool.fetch("""
            SELECT o.order_id, o.user_id, o.amount, o.quantity, o.status, o.paid_at, o.created_at,
                c.title AS coupon_title, c.created_by AS admin_id,
                u.full_name AS buyer_name, u.username AS buyer_username
            FROM orders o LEFT JOIN coupons c ON o.coupon_id = c.id
            LEFT JOIN users u ON o.user_id = u.telegram_id
            WHERE o.status IN ('paid','delivered')
            ORDER BY o.paid_at DESC NULLS LAST LIMIT 100
        """)

        # Daily revenue (30 days)
        daily = await pool.fetch("""
            SELECT DATE(paid_at) AS day, COUNT(*) AS order_count,
                COALESCE(SUM(amount), 0) AS revenue
            FROM orders WHERE status IN ('paid','delivered')
                AND paid_at >= NOW() - interval '30 days'
            GROUP BY DATE(paid_at) ORDER BY day ASC
        """)

        # Admin names lookup
        all_admin_ids = set(ADMIN_IDS) | db_admins
        for r in admin_rows:
            if r["admin_id"]:
                all_admin_ids.add(r["admin_id"])
        for r in product_rows:
            if r["admin_id"]:
                all_admin_ids.add(r["admin_id"])

        admin_names = {}
        for aid in all_admin_ids:
            u = await pool.fetchrow("SELECT full_name, username FROM users WHERE telegram_id = $1", aid)
            admin_names[aid] = (u["full_name"] or u["username"] or str(aid)) if u else str(aid)

        def dt(v):
            return v.isoformat() if v else None

        data = {
            "summary": {
                "total_users": user_count,
                "total_orders": sales["total_orders"],
                "total_paid": sales["total_paid"],
                "total_pending": sales["total_pending"],
                "total_expired": sales["total_expired"],
                "total_revenue": float(sales["total_revenue"]),
            },
            "admin_sales": [
                {"admin_id": r["admin_id"], "admin_name": admin_names.get(r["admin_id"], str(r["admin_id"])),
                 "products_added": r["products_added"], "total_sold": r["total_sold"],
                 "total_revenue": float(r["total_revenue"]), "pending_orders": r["pending_orders"],
                 "pending_revenue": float(r["pending_revenue"])} for r in admin_rows
            ],
            "products": [
                {"coupon_id": r["coupon_id"], "title": r["title"], "price": float(r["price"]),
                 "stock": r["stock"], "is_active": r["is_active"],
                 "admin_id": r["admin_id"], "admin_name": admin_names.get(r["admin_id"], "Unknown") if r["admin_id"] else "Unknown",
                 "created_at": dt(r["created_at"]), "sold_count": r["sold_count"],
                 "revenue": float(r["revenue"]), "pending_count": r["pending_count"],
                 "codes_sold": r["codes_sold"], "codes_available": r["codes_available"]} for r in product_rows
            ],
            "recent_sales": [
                {"order_id": r["order_id"], "user_id": r["user_id"], "amount": float(r["amount"]),
                 "quantity": r["quantity"], "status": r["status"], "paid_at": dt(r["paid_at"]),
                 "created_at": dt(r["created_at"]), "coupon_title": r["coupon_title"],
                 "admin_id": r["admin_id"],
                 "admin_name": admin_names.get(r["admin_id"], "Unknown") if r["admin_id"] else "Unknown",
                 "buyer_name": r["buyer_name"] or "Unknown"} for r in recent
            ],
            "daily_revenue": [
                {"day": dt(r["day"]), "order_count": r["order_count"],
                 "revenue": float(r["revenue"])} for r in daily
            ],
            "admin_names": {str(k): v for k, v in admin_names.items()},
        }

        return web.json_response(data)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return web.json_response({"error": str(e)}, status=500)


async def handle_static(request):
    filename = request.match_info.get("filename", "")
    filepath = STATIC_DIR / filename
    if filepath.exists() and filepath.is_file():
        return web.FileResponse(filepath)
    return web.Response(text="Not found", status=404)


# ── App Factory ───────────────────────────────────────────

def create_app():
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_post("/api/verify", handle_verify)
    app.router.add_get("/api/analytics", handle_analytics)
    app.router.add_get("/static/{filename}", handle_static)

    # CORS headers for Telegram WebApp
    @web.middleware
    async def cors_middleware(request, handler):
        resp = await handler(request)
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return resp

    app.middlewares.append(cors_middleware)
    return app


if __name__ == "__main__":
    if not DATABASE_URL:
        print("❌ DATABASE_URL is required! Set it in .env or environment.")
        sys.exit(1)
    if not ADMIN_IDS:
        print("❌ ADMIN_IDS is required!")
        sys.exit(1)

    print(f"🚀 DreamX Analytics Server starting on port {PORT}")
    print(f"📊 Static dir: {STATIC_DIR}")
    print(f"👑 Admin IDs: {ADMIN_IDS}")
    print(f"🔗 Database: {DATABASE_URL[:30]}...")

    app = create_app()
    web.run_app(app, host="0.0.0.0", port=PORT, print=lambda msg: print(f"✅ {msg}"))
