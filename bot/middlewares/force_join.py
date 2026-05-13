"""
DreamX Coupon Bot — Force Join Middleware
Checks if the user has joined the mandatory channel/group(s) before allowing access.
Supports multiple channels (comma-separated) and both @username and numeric ID formats.
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

        # Only process private chat messages/callbacks
        if not isinstance(event, (Message, CallbackQuery)):
            return await handler(event, data)

        user = event.from_user
        if not user:
            return await handler(event, data)

        # Determine chat type — skip middleware for group/channel messages
        if isinstance(event, Message) and event.chat.type != "private":
            return await handler(event, data)
        if isinstance(event, CallbackQuery) and event.message and event.message.chat.type != "private":
            return await handler(event, data)

        # Admins bypass force join
        if Config.is_admin(user.id):
            return await handler(event, data)

        try:
            settings = await db.get_bot_settings()
            force_channel_raw = settings.get("force_channel") if settings else None

            if not force_channel_raw:
                return await handler(event, data)

            # Support multiple channels: "-100123,@channel2"
            channels = [ch.strip() for ch in force_channel_raw.split(",") if ch.strip()]
            if not channels:
                return await handler(event, data)

            bot = data.get("bot") or event.bot

            # Check membership in ALL configured channels
            not_joined = []
            for channel in channels:
                try:
                    chat_id = int(channel) if channel.lstrip("-").isdigit() else channel
                    member = await bot.get_chat_member(chat_id=chat_id, user_id=user.id)
                    if member.status in ("left", "kicked"):
                        # Get channel info for the join button
                        try:
                            chat_info = await bot.get_chat(chat_id)
                            invite = chat_info.invite_link
                            title = chat_info.title or str(channel)
                        except Exception:
                            invite = None
                            title = str(channel)

                        not_joined.append({
                            "channel": channel,
                            "title": title,
                            "invite": invite,
                        })
                except Exception as e:
                    logger.warning(f"Force join check failed for {channel}: {e}")
                    # If bot is not admin or channel is invalid, skip this channel
                    continue

            if not_joined:
                # User hasn't joined one or more channels — block them
                buttons = []
                for ch in not_joined:
                    if ch["invite"]:
                        url = ch["invite"]
                    elif str(ch["channel"]).startswith("@"):
                        url = f"https://t.me/{ch['channel'].replace('@', '')}"
                    else:
                        # For numeric IDs, we need the invite link (already tried above)
                        # If no invite link available, try constructing from bot info
                        url = None

                    if url:
                        buttons.append([InlineKeyboardButton(
                            text="📢 Join Channel",
                            url=url,
                        )])

                buttons.append([InlineKeyboardButton(
                    text="✅ I have joined",
                    callback_data="check_join_status"
                )])

                kb = InlineKeyboardMarkup(inline_keyboard=buttons)

                text = (
                    "🚨 *Mandatory Channel Join*\n\n"
                    "You must join our channel to use this bot\\!\n\n"
                    "👇 Join using the button below, then tap *✅ I have joined*\\."
                )

                if isinstance(event, CallbackQuery):
                    if event.data == "check_join_status":
                        await event.answer(
                            "❌ You have not joined yet! Join the channel first.",
                            show_alert=True
                        )
                        return
                    try:
                        await event.message.answer(text, parse_mode="MarkdownV2", reply_markup=kb)
                        await event.answer()
                    except Exception:
                        pass
                    return

                elif isinstance(event, Message):
                    await event.answer(text, parse_mode="MarkdownV2", reply_markup=kb)
                    return

            # User has joined all channels
            if isinstance(event, CallbackQuery) and event.data == "check_join_status":
                await event.answer("✅ Thank you for joining!", show_alert=True)
                from bot.keyboards.main_menu import main_menu_kb
                from bot.utils.helpers import escape_md
                first = escape_md(user.first_name or "there")
                await event.message.answer(
                    f"✅ Thanks for joining, *{first}*\\! You can now use the bot\\.",
                    parse_mode="MarkdownV2",
                    reply_markup=main_menu_kb(user.id)
                )
                try:
                    await event.message.delete()
                except Exception:
                    pass
                return

        except Exception as e:
            logger.error(f"ForceJoinMiddleware error: {e}")
            # If middleware crashes, let user through to avoid locking everyone out

        return await handler(event, data)
