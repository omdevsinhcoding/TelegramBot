"""
DreamX Coupon Bot — Data Cleanup Script
Clears ALL coupon/giveaway data for a fresh start.
PRESERVES: users, orders (history), wallet_transactions, referrals, transactions.

Usage:
    python clear_coupon_data.py           # Execute cleanup
    python clear_coupon_data.py --dry-run # Preview what will be deleted

IMPORTANT: Run 'python run_migration.py' FIRST to ensure schema is up-to-date
           (especially orders.coupon_id nullable migration).
"""

import asyncio
import asyncpg
import os
import sys
from dotenv import load_dotenv

# Force UTF-8 output on Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

load_dotenv()

DRY_RUN = "--dry-run" in sys.argv


async def main():
    url = os.getenv("DATABASE_URL")
    if not url:
        print("ERROR: DATABASE_URL not found in .env")
        return

    print("=" * 50)
    print("  DreamX Bot — Data Cleanup Script")
    print("  Mode: DRY RUN (preview)" if DRY_RUN else "  Mode: LIVE (will delete data!)")
    print("=" * 50)

    conn = await asyncpg.connect(url)
    print("\n✅ Connected to database.\n")

    # ── Step 0: Count what exists ──
    counts = {}
    tables_to_check = [
        "coupons", "coupon_codes", "coupon_categories",
        "free_coupons", "free_coupon_codes", "free_coupon_claims",
        "admin_extractions", "giveaway_logs", "promotional_losses",
        "referral_rewards", "referral_claims",
        "orders", "users", "wallet_transactions", "referrals", "transactions",
    ]

    print("📊 Current Data Summary:")
    print("-" * 40)
    for table in tables_to_check:
        try:
            count = await conn.fetchval(f"SELECT COUNT(*) FROM {table}")
            counts[table] = count
            marker = "🗑️" if table in [
                "coupons", "coupon_codes", "coupon_categories",
                "free_coupons", "free_coupon_codes", "free_coupon_claims",
                "admin_extractions", "giveaway_logs", "promotional_losses",
                "referral_rewards", "referral_claims",
            ] else "✅"
            print(f"  {marker} {table}: {count} rows")
        except Exception:
            counts[table] = 0
            print(f"  ⚠️  {table}: table not found")

    print("-" * 40)
    print("  🗑️ = Will be deleted")
    print("  ✅ = Will be PRESERVED")

    if DRY_RUN:
        print("\n🔍 DRY RUN — No changes made.")
        await conn.close()
        return

    # Confirm
    print("\n⚠️  This will DELETE all coupon/giveaway data!")
    print("    Orders, users, wallets, and referrals will be PRESERVED.")
    confirm = input("\n    Type 'YES' to proceed: ")
    if confirm.strip() != "YES":
        print("❌ Aborted.")
        await conn.close()
        return

    print("\n🔄 Starting cleanup...\n")

    async with conn.transaction():
        # ── Step 1: NULL out coupon_id on orders (preserve order history) ──
        result = await conn.execute("UPDATE orders SET coupon_id = NULL WHERE coupon_id IS NOT NULL")
        print(f"  ✅ Detached {result.split()[-1]} orders from coupons")

        # ── Step 2: Clear giveaway/free coupon data ──
        result = await conn.execute("DELETE FROM free_coupon_claims")
        print(f"  🗑️  Deleted free_coupon_claims: {result}")

        result = await conn.execute("DELETE FROM free_coupon_codes")
        print(f"  🗑️  Deleted free_coupon_codes: {result}")

        result = await conn.execute("DELETE FROM giveaway_logs")
        print(f"  🗑️  Deleted giveaway_logs: {result}")

        result = await conn.execute("DELETE FROM free_coupons")
        print(f"  🗑️  Deleted free_coupons: {result}")

        # ── Step 3: Clear referral rewards (NOT referrals themselves!) ──
        result = await conn.execute("DELETE FROM referral_claims")
        print(f"  🗑️  Deleted referral_claims: {result}")

        result = await conn.execute("DELETE FROM referral_rewards")
        print(f"  🗑️  Deleted referral_rewards: {result}")

        # ── Step 4: Clear promotional loss tracking ──
        result = await conn.execute("DELETE FROM promotional_losses")
        print(f"  🗑️  Deleted promotional_losses: {result}")

        # ── Step 5: Clear admin extractions ──
        result = await conn.execute("DELETE FROM admin_extractions")
        print(f"  🗑️  Deleted admin_extractions: {result}")

        # ── Step 6: Clear coupon codes ──
        result = await conn.execute("DELETE FROM coupon_codes")
        print(f"  🗑️  Deleted coupon_codes: {result}")

        # ── Step 7: Clear coupons ──
        result = await conn.execute("DELETE FROM coupons")
        print(f"  🗑️  Deleted coupons: {result}")

        # ── Step 8: Clear categories ──
        result = await conn.execute("DELETE FROM coupon_categories")
        print(f"  🗑️  Deleted coupon_categories: {result}")

        # ── Step 9: Reset sequences ──
        sequences = [
            ("coupons_id_seq", "coupons"),
            ("coupon_codes_id_seq", "coupon_codes"),
            ("coupon_categories_id_seq", "coupon_categories"),
            ("free_coupons_id_seq", "free_coupons"),
            ("free_coupon_codes_id_seq", "free_coupon_codes"),
            ("referral_rewards_id_seq", "referral_rewards"),
        ]
        for seq_name, table_name in sequences:
            try:
                await conn.execute(f"ALTER SEQUENCE {seq_name} RESTART WITH 1")
                print(f"  🔄 Reset sequence: {seq_name}")
            except Exception:
                pass  # Sequence might not exist

    print("\n" + "=" * 50)
    print("  ✅ CLEANUP COMPLETE!")
    print("=" * 50)
    print("\n  Preserved:")
    print(f"    👥 Users: {counts.get('users', 0)}")
    print(f"    🧾 Orders: {counts.get('orders', 0)} (coupon_id set to NULL)")
    print(f"    💰 Wallet Transactions: {counts.get('wallet_transactions', 0)}")
    print(f"    🤝 Referrals: {counts.get('referrals', 0)}")
    print(f"    💳 Transactions: {counts.get('transactions', 0)}")
    print("\n  You can now add new coupons/categories from the Admin Panel.")

    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
