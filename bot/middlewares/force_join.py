"""
DreamX Coupon Bot — Force Join Middleware
Checks if the user has joined the mandatory channel (if configured).
"""

from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from bot.config import Config
from bot.database import queries as db
from bot.utils.logger import logger

class ForceJoinMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Message | CallbackQuery, Dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: Dict[str, Any]
    ) -> Any:
        
        # We only process messages or callbacks
        if not isinstance(event, (Message, CallbackQuery)):
            return await handler(event, data)
        
        user = event.from_user
        if not user:
            return await handler(event, data)
            
        # Admins can bypass force join
        if Config.is_admin(user.id):
            return await handler(event, data)
            
        try:
            settings = await db.get_bot_settings()
            force_channel = settings.get("force_channel") if settings else None
            
            if force_channel:
                bot = data.get("bot") or event.bot
                
                # Check membership
                member = await bot.get_chat_member(chat_id=force_channel, user_id=user.id)
                
                # If they are not member (left, kicked, restricted, etc), block them.
                if member.status in ['left', 'kicked', 'restricted']:
                    
                    kb = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="📢 Join Channel", url=f"https://t.me/{force_channel.replace('@', '')}")],
                        [InlineKeyboardButton(text="✅ I have joined", callback_data="check_join_status")]
                    ])
                    
                    text = (
                        "🚨 *Mandatory Channel Join*\n\n"
                        "You must join our official channel to use this bot!\n"
                        "Please join using the button below and then click *I have joined*."
                    )
                    
                    # Handle CallbackQuery
                    if isinstance(event, CallbackQuery):
                        if event.data == "check_join_status":
                            await event.answer("You have not joined the channel yet!", show_alert=True)
                            return
                        # If it's a callback, we can edit the message or send a new one
                        try:
                            await event.message.answer(text, parse_mode="MarkdownV2", reply_markup=kb)
                            await event.answer()
                        except Exception:
                            pass
                        return
                    
                    # Handle Message
                    elif isinstance(event, Message):
                        await event.answer(text, parse_mode="MarkdownV2", reply_markup=kb)
                        return
                        
                # If they are a member, allow them through
                if isinstance(event, CallbackQuery) and event.data == "check_join_status":
                    await event.answer("Thank you for joining!", show_alert=True)
                    # Let the check_join_status callback pass or drop it here. We can drop it.
                    # Send them the main menu or a simple message so they can continue
                    from bot.keyboards.main_menu import main_menu_kb
                    from bot.utils.helpers import escape_md
                    first = escape_md(user.first_name or "there")
                    await event.message.answer(f"Thanks for joining, *{first}*! You can now use the bot.", parse_mode="MarkdownV2", reply_markup=main_menu_kb(user.id))
                    # Optionally delete the "Mandatory join" message
                    try:
                        await event.message.delete()
                    except Exception:
                        pass
                    return
                    
        except Exception as e:
            logger.error(f"ForceJoinMiddleware error: {e}")
            # If the bot is not admin in the channel, it throws an error.
            # We should probably let the user through if the bot is misconfigured
            # to avoid locking out everyone.
            
        return await handler(event, data)
