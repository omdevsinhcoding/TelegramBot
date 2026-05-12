# 💎 DreamX Coupon Bot

A professional Telegram bot for selling coupons with UPI payment integration (Paytm QR + BharatPe), built with aiogram 3.x and PostgreSQL.

---

## 📁 Project Structure

```
TelegramBot/
├── bot/
│   ├── config.py              # Environment config loader
│   ├── main.py                # Dispatcher + routers + background tasks
│   ├── handlers/
│   │   ├── start.py           # /start command
│   │   ├── menu.py            # Main menu navigation
│   │   ├── coupons.py         # Coupon browsing
│   │   ├── wallet.py          # Wallet management
│   │   ├── purchase.py        # Buy flow + QR generation
│   │   └── admin.py           # Full admin panel
│   ├── services/
│   │   ├── user_service.py    # User business logic
│   │   ├── wallet_service.py  # Wallet credit/debit
│   │   ├── coupon_service.py  # Coupon CRUD
│   │   ├── order_service.py   # Order lifecycle
│   │   └── payment_service.py # Background payment poller
│   ├── database/
│   │   ├── connection.py      # asyncpg pool
│   │   └── queries.py         # All SQL queries
│   ├── payments/
│   │   ├── upi.py             # UPI URL + QR generation
│   │   └── verifier.py        # Paytm + BharatPe verification
│   ├── keyboards/
│   │   ├── common.py          # Shared buttons
│   │   ├── main_menu.py       # Main menu KB
│   │   ├── coupon_kb.py       # Coupon KBs
│   │   ├── wallet_kb.py       # Wallet KBs
│   │   └── admin_kb.py        # Admin KBs
│   └── utils/
│       ├── logger.py          # Logging setup
│       ├── helpers.py         # Utility functions
│       └── decorators.py      # @admin_only, @error_handler
├── sql/
│   └── schema.sql             # PostgreSQL schema
├── .env.example               # Environment template
├── requirements.txt           # Python dependencies
├── run.py                     # Entry point
└── README.md
```

---

## 🚀 Quick Start

```bash
cp .env.example .env       # Edit with your real values
pip install -r requirements.txt
python run.py
```

---

## 🔧 Configuration (.env)

| Variable | Description |
|----------|-------------|
| `BOT_TOKEN` | Telegram Bot token from @BotFather |
| `ADMIN_IDS` | Comma-separated admin Telegram IDs |
| `DATABASE_URL` | PostgreSQL connection string |
| `PAYTM_MERCHANT_ID` | Paytm MID (for status check) |
| `PAYTM_UPI_ID` | Paytm QR VPA (e.g. paytmqr...@paytm) |
| `PAYTM_QR_CODE` | paytmqr param for UPI URL |
| `BHARATPE_MERCHANT_ID` | BharatPe merchant ID |
| `BHARATPE_TOKEN` | BharatPe API token |

---

## 💳 Payment Flows

**Paytm**: Bot generates QR → user pays → bot polls `GET /order/status` with ORDERID → auto-verifies

**BharatPe**: Bot generates QR → user pays → bot fetches `GET /merchant/transactions` → matches by UTR → auto-verifies

---

## 🔒 Security

- All secrets via `.env` — zero hardcoded
- Paytm: verify STATUS + MID + ORDERID + TXNAMOUNT
- BharatPe: match by bankReferenceNo (UTR)
- Atomic stock reduction prevents overselling
- `@admin_only` decorator on all admin handlers
