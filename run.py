"""
DreamX Coupon Bot — Entry Point
Run this file to start the bot.

For 24/7 hosting on AlwaysData:
  - Use AlwaysData → Advanced → Processes to run this script
  - Command: python3 /home/YOUR_ACCOUNT/TelegramBot/run.py
  - Working directory: /home/YOUR_ACCOUNT/TelegramBot
  - The process manager will auto-restart on crash
"""

import asyncio
import signal
import sys
from bot.main import main


def handle_signal(signum, frame):
    """Graceful shutdown on SIGTERM/SIGINT."""
    sys.exit(0)


if __name__ == "__main__":
    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    # Run with proper event loop policy
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
