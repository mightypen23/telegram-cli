"""
Telegram Bot service – bridges Telegram Desktop/Mobile to the local AI assistant.

Listens for commands and queries in direct private messages, group chats,
and channels with discussion groups where @mightypen_bot is mentioned.
Restricted exclusively to the account owner for security and privacy.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from telethon import Button, TelegramClient, events

from app.services.ai import AIAssistantService, Draft

logger = logging.getLogger(__name__)


class AIBotService:
    """Manages the personal assistant Telegram Bot."""

    def __init__(
        self,
        bot_client: TelegramClient,
        user_client: TelegramClient,
        ai_service: AIAssistantService,
        owner_id: int | None = None,
    ) -> None:
        self.bot = bot_client
        self.user = user_client
        self.ai = ai_service
        self.owner_id = owner_id
        self.owner_username: str = ""
        self.bot_username: str = ""
        self.bot_id: int | None = None
        self._running = False
        self._event_handlers: list[Any] = []

    async def start(self, bot_token: str) -> None:
        """Start the bot client and register event listeners."""
        if self._running:
            return

        if not self.bot.is_connected():
            await self.bot.start(bot_token=bot_token)

        bot_me = await self.bot.get_me()
        self.bot_username = getattr(bot_me, "username", "") or "bot"
        self.bot_id = bot_me.id

        if self.owner_id is None:
            user_me = await self.user.get_me()
            if user_me:
                self.owner_id = user_me.id
                self.owner_username = getattr(user_me, "username", "") or str(user_me.id)

        # Register message and callback handlers
        self.bot.add_event_handler(self._on_message, events.NewMessage)
        self.bot.add_event_handler(self._on_callback, events.CallbackQuery)

        self._running = True
        logger.info(
            "AI Assistant Bot @%s started. Restricted to owner ID %s (@%s).",
            self.bot_username,
            self.owner_id,
            self.owner_username,
        )

    async def stop(self) -> None:
        """Stop the bot client."""
        if not self._running:
            return
        self._running = False
        try:
            await self.bot.disconnect()
        except Exception:
            pass

    @property
    def is_running(self) -> bool:
        return self._running and self.bot.is_connected()

    async def _is_owner(self, event: events.NewMessage.Event) -> bool:
        """Check if the sender is the account owner (@alezwel)."""
        sender_id = getattr(event, "sender_id", None)
        if sender_id and sender_id == self.owner_id:
            return True
        try:
            sender = await event.get_sender()
            if sender:
                username = getattr(sender, "username", "") or ""
                if username:
                    if self.owner_username and username.lower() == self.owner_username.lower():
                        return True
                    if username.lower() == "alezwel":
                        return True
                if getattr(sender, "id", None) == self.owner_id:
                    return True
        except Exception:
            pass
        return False

    # ------------------------------------------------------------------ #
    #  Event Handlers
    # ------------------------------------------------------------------ #

    async def _on_message(self, event: events.NewMessage.Event) -> None:
        """Handle incoming messages across private chats, groups, and channels."""
        raw_text = (event.raw_text or "").strip()
        if not raw_text:
            return

        is_private = event.is_private
        is_group_or_channel = event.is_group or event.is_channel

        # In groups/channels, check if bot is explicitly mentioned or replied to
        if is_group_or_channel:
            mentioned = False
            bot_handle = f"@{self.bot_username}".lower()
            if bot_handle in raw_text.lower():
                mentioned = True
            elif event.is_reply:
                reply_msg = await event.get_reply_message()
                if reply_msg and reply_msg.sender_id == self.bot_id:
                    mentioned = True

            if not mentioned:
                return

        # Check if the sender is the account owner
        is_owner = await self._is_owner(event)

        # Process private commands (/start, /help, /confirm, /cancel, /clear)
        cmd = raw_text.lower()
        if cmd in ("/start", "/help"):
            await self._send_help_message(event)
            return

        if cmd in ("/confirm", "/send", "confirm", "send", "yes"):
            if not is_owner:
                await event.reply("Only the account owner can confirm sending messages.")
                return
            latest_draft = self.ai.get_latest_draft()
            if latest_draft:
                success, result_msg = await self.ai.confirm_draft(latest_draft.id)
                await event.reply(result_msg)
            else:
                await event.reply("No pending message draft found to send.")
            return

        if cmd in ("/cancel", "cancel", "no"):
            if not is_owner:
                return
            latest_draft = self.ai.get_latest_draft()
            if latest_draft:
                _, result_msg = self.ai.cancel_draft(latest_draft.id)
                await event.reply(result_msg)
            else:
                await event.reply("No pending message draft to cancel.")
            return

        if cmd in ("/clear", "/reset", "clear", "reset"):
            self.ai.clear_session_history(str(event.chat_id))
            await event.reply("🧹 Conversation memory cleared for this chat.", parse_mode="markdown")
            return

        # Strip bot handle if in group/channel
        prompt = raw_text
        if is_group_or_channel and self.bot_username:
            pattern = re.compile(rf"@{re.escape(self.bot_username)}\b", re.IGNORECASE)
            prompt = pattern.sub("", prompt).strip()

        # Build group/channel context with recent conversation messages
        chat_context: str | None = None
        if is_group_or_channel:
            try:
                chat = await event.get_chat()
                chat_title = getattr(chat, "title", "Group/Channel")
                chat_context = f"Active in group: '{chat_title}'"
                if event.is_reply:
                    reply_msg = await event.get_reply_message()
                    if reply_msg:
                        sender = await reply_msg.get_sender()
                        s_name = getattr(sender, "first_name", "") or getattr(sender, "username", "") or "User"
                        chat_context += f"\nReplying to {s_name}: \"{reply_msg.text or ''}\""

                # Retrieve last few messages from group for ongoing context
                try:
                    msgs = await self.bot.get_messages(event.chat_id, limit=8)
                    recent_lines = []
                    for m in reversed(msgs):
                        if m.id == event.id:
                            continue
                        m_sender = await m.get_sender()
                        m_name = getattr(m_sender, "first_name", "") or getattr(m_sender, "username", "") or "User"
                        text_snip = (m.text or "").strip()
                        if text_snip:
                            recent_lines.append(f"{m_name}: {text_snip}")
                    if recent_lines:
                        chat_context += "\nRecent conversation in this group:\n" + "\n".join(recent_lines)
                except Exception:
                    pass
            except Exception:
                pass

        session_id = str(event.chat_id)
        owner_info = (
            f"@{self.owner_username} (User ID: {self.owner_id})"
            if self.owner_username
            else f"User ID: {self.owner_id}"
        )

        try:
            # Show native Telegram "typing..." status indicator while thinking
            try:
                action_cm = self.bot.action(event.chat_id, "typing")
                if hasattr(action_cm, "__aenter__"):
                    async with action_cm:
                        response = await self.ai.ask(
                            prompt,
                            chat_context=chat_context,
                            session_id=session_id,
                            owner_info=owner_info,
                            is_owner=is_owner,
                        )
                else:
                    response = await self.ai.ask(
                        prompt,
                        chat_context=chat_context,
                        session_id=session_id,
                        owner_info=owner_info,
                        is_owner=is_owner,
                    )
            except Exception:
                response = await self.ai.ask(
                    prompt,
                    chat_context=chat_context,
                    session_id=session_id,
                    owner_info=owner_info,
                    is_owner=is_owner,
                )

            if response.draft:
                draft_text = (
                    f"📝 **Message Draft Prepared**\n\n"
                    f"**To:** {response.draft.recipient}\n"
                    f"**Message:**\n> {response.draft.message}\n\n"
                    "Would you like me to send this message on your behalf?"
                )
                buttons = [
                    [
                        Button.inline("✅ Send Message", data=f"send_draft:{response.draft.id}".encode("utf-8")),
                        Button.inline("❌ Cancel", data=f"cancel_draft:{response.draft.id}".encode("utf-8")),
                    ]
                ]
                await event.reply(draft_text, buttons=buttons, parse_mode="markdown")
            else:
                reply_text = response.text or "I processed your request."
                await event.reply(reply_text, parse_mode="markdown")
        except Exception as exc:
            logger.error("Error processing AI request: %s", exc, exc_info=True)
            await event.reply(f"❌ Error processing request: {exc}")

    async def _on_callback(self, event: events.CallbackQuery.Event) -> None:
        """Handle inline button clicks for draft confirmation / cancellation."""
        is_owner = False
        if event.sender_id and event.sender_id == self.owner_id:
            is_owner = True
        else:
            try:
                sender = await event.get_sender()
                if sender:
                    username = getattr(sender, "username", "") or ""
                    if username and (username.lower() == self.owner_username.lower() or username.lower() == "alezwel"):
                        is_owner = True
            except Exception:
                pass

        if not is_owner:
            await event.answer("Only the account owner can confirm message drafts.", alert=True)
            return

        data = event.data.decode("utf-8", errors="ignore")

        if data.startswith("send_draft:"):
            draft_id = data.split(":", 1)[1]
            success, msg = await self.ai.confirm_draft(draft_id)
            await event.edit(msg, buttons=None, parse_mode="markdown")
            await event.answer("Message sent!" if success else "Failed to send")

        elif data.startswith("cancel_draft:"):
            draft_id = data.split(":", 1)[1]
            success, msg = self.ai.cancel_draft(draft_id)
            await event.edit(msg, buttons=None, parse_mode="markdown")
            await event.answer("Draft cancelled")

    async def _send_help_message(self, event: events.NewMessage.Event) -> None:
        """Send welcome and help message to owner."""
        text = (
            f"👋 **Welcome to your Personal AI Assistant!**\n\n"
            f"I am connected to your Telegram account and powered locally by Ollama (`{self.ai.model}`).\n\n"
            f"**What I can do for you:**\n"
            f"🔍 **Search Chats & Context:**\n"
            f"  • *\"Find a chat with Bob where we talked about project deadlines\"*\n"
            f"  • *\"What did Sarah say about the meeting location?\"*\n"
            f"  • *\"Find messages about budget in the Marketing group\"*\n\n"
            f"✉️ **Draft & Send Messages:**\n"
            f"  • *\"Send a message to @alice saying I will be 15 minutes late\"*\n"
            f"  • *\"Draft a reply to Bob's last message saying confirmed\"*\n"
            f"  *(All messages show a preview draft first for your confirmation)*\n\n"
            f"👥 **In Groups & Channels:**\n"
            f"  • Add me to any group or channel discussion and mention `@{self.bot_username}` to ask questions or summarize discussions!\n\n"
            f"🧠 **Context Memory:**\n"
            f"  • I remember recent turns in our conversation for follow-up questions.\n"
            f"  • Type `/clear` or `/reset` anytime to reset conversation memory.\n\n"
            f"🔒 **Security:**\n"
            f"  • Only you (@{self.owner_username or 'owner'}) can command me or view your private messages."
        )
        await event.reply(text, parse_mode="markdown")
