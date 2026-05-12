import asyncio
from bot.database.connection import init_db
from bot.database import queries as db

async def test():
    try:
        await init_db()
        print("DB init ok")
        bid = await db.create_broadcast(12345, "test msg", 1)
        print(f"Broadcast created: {bid}")
        await db.update_broadcast(bid, 1, 0, "completed")
        print("Broadcast updated")
        await db.add_admin_log(12345, "broadcast", None, str(bid), "test log")
        print("Log added")
    except Exception as e:
        print(f"ERROR: {e}")

if __name__ == "__main__":
    asyncio.run(test())
