"""
DreamX Coupon Bot — FSM Clear Middleware

Automatically clears stale FSM state when user presses a static keyboard button
or sends a command. This prevents FSM text-input handlers (e.g., BharatPeStates.waiting_utr)
from intercepting unrelated menu button presses.

MUST be registered as an outer_middleware on dp.message so it runs BEFORE
handler/filter resolution. Outer middlewares can modify FSM state and affect
which handler aiogram selects.
"""

from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from bot.utils.logger import logger


# All static keyboard button texts used in the reply keyboard.
# If the user presses any of these while in an FSM state, clear the state
# so the correct menu handler picks up the message.
MENU_BUTTON_TEXTS = frozenset({
    # main_menu_kb buttons
    "🛍️ Buy Vouchers",
    "📦 My Orders",
    "📊 View Stock",
    "🎟️ Recover Coupon",
    "🎁 Refer & Earn",
    "🆘 Support",
    "⚠️ Disclaimer",
    "📢 Our Channels",
    "👑 Admin Panel",
    "💰 Wallet",
})


class FSMClearMiddleware(BaseMiddleware):
    """Clear FSM state when a known menu button or command is pressed during text input.
    
    This solves the systemic issue where pressing a keyboard button during
    any FSM text-input state (BharatPe UTR entry, admin field edit, referral
    code entry, etc.) causes the FSM handler to intercept and misinterpret
    the menu button text as user input.
    """

    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: Dict[str, Any],
    ) -> Any:
        # Only process text messages in private chats
        if not isinstance(event, Message) or not event.text:
            return await handler(event, data)

        if event.chat.type != "private":
            return await handler(event, data)

        text = event.text.strip()

        # Check if this is a menu button press or a command (like /start, /cancel)
        is_menu_button = text in MENU_BUTTON_TEXTS
        is_command = text.startswith("/")

        if is_menu_button or is_command:
            state: FSMContext | None = data.get("state")
            if state:
                try:
                    current_state = await state.get_state()
                    if current_state is not None:
                        # Don't clear admin FSM states when admin presses admin panel button
                        # (they might be legitimately navigating admin features)
                        if text == "👑 Admin Panel" and "AdminStates" in current_state:
                            return await handler(event, data)
                        
                        logger.info(
                            f"[FSM_CLEAR] Cleared stale state '{current_state}' for user "
                            f"{event.from_user.id} (pressed: '{text[:30]}')"
                        )
                        await state.clear()
                except Exception as e:
                    logger.warning(f"[FSM_CLEAR] Error checking state: {e}")

        return await handler(event, data)
