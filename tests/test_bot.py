"""Tests for app.services.bot – Telegram bot bridge and owner security."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.ai import AIResponse, Draft
from app.services.bot import AIBotService


@pytest.fixture
def mock_bot_client():
    client = MagicMock()
    client.is_connected = MagicMock(return_value=True)
    client.start = AsyncMock()
    client.disconnect = AsyncMock()
    client.add_event_handler = MagicMock()
    bot_user = MagicMock()
    bot_user.id = 9181525259
    bot_user.username = "mightypen_bot"
    client.get_me = AsyncMock(return_value=bot_user)
    return client


@pytest.fixture
def mock_user_client():
    client = MagicMock()
    user_me = MagicMock()
    user_me.id = 7522968153
    user_me.username = "alezwel"
    client.get_me = AsyncMock(return_value=user_me)
    return client


@pytest.fixture
def mock_ai_service():
    ai = MagicMock()
    ai.model = "qwen2.5:3b"
    ai.ask = AsyncMock(return_value=AIResponse(text="AI response here"))
    ai.get_latest_draft = MagicMock(return_value=None)
    ai.confirm_draft = AsyncMock(return_value=(True, "Message sent!"))
    ai.cancel_draft = MagicMock(return_value=(True, "Draft cancelled."))
    return ai


class TestBotAuthorizationAndCommands:
    @pytest.mark.asyncio
    async def test_bot_start(self, mock_bot_client, mock_user_client, mock_ai_service):
        bot = AIBotService(mock_bot_client, mock_user_client, mock_ai_service)
        await bot.start("fake_token")
        assert bot.is_running is True
        assert bot.owner_id == 7522968153
        assert bot.bot_username == "mightypen_bot"

    @pytest.mark.asyncio
    async def test_private_message_public_user_answers_like_grok(
        self, mock_bot_client, mock_user_client, mock_ai_service
    ):
        bot = AIBotService(mock_bot_client, mock_user_client, mock_ai_service, owner_id=7522968153)
        mock_ai_service.ask = AsyncMock(return_value=AIResponse(text="Hello human! What can I do for you?"))

        event = MagicMock()
        event.chat_id = 999999999
        event.raw_text = "Hello bot"
        event.is_private = True
        event.is_group = False
        event.is_channel = False
        event.sender_id = 999999999  # Public user
        event.get_sender = AsyncMock(return_value=None)
        event.reply = AsyncMock()

        await bot._on_message(event)
        mock_ai_service.ask.assert_awaited_once()
        args, kwargs = mock_ai_service.ask.call_args
        assert args[0] == "Hello bot"
        assert kwargs["is_owner"] is False
        event.reply.assert_awaited_once_with("Hello human! What can I do for you?", parse_mode="markdown")

    @pytest.mark.asyncio
    async def test_non_owner_cannot_confirm_draft(
        self, mock_bot_client, mock_user_client, mock_ai_service
    ):
        bot = AIBotService(mock_bot_client, mock_user_client, mock_ai_service, owner_id=7522968153)
        event = MagicMock()
        event.chat_id = 999999999
        event.raw_text = "/confirm"
        event.is_private = True
        event.is_group = False
        event.is_channel = False
        event.sender_id = 999999999
        event.get_sender = AsyncMock(return_value=None)
        event.reply = AsyncMock()

        await bot._on_message(event)
        event.reply.assert_awaited_once()
        assert "Only the account owner" in event.reply.call_args[0][0]
        mock_ai_service.confirm_draft.assert_not_called()

    @pytest.mark.asyncio
    async def test_owner_recognized_by_username(
        self, mock_bot_client, mock_user_client, mock_ai_service
    ):
        bot = AIBotService(mock_bot_client, mock_user_client, mock_ai_service, owner_id=7522968153)
        bot.owner_username = "alezwel"

        sender = MagicMock()
        sender.username = "alezwel"
        sender.id = 88888888

        event = MagicMock()
        event.sender_id = 88888888
        event.get_sender = AsyncMock(return_value=sender)

        is_owner = await bot._is_owner(event)
        assert is_owner is True

    @pytest.mark.asyncio
    async def test_private_message_authorized_owner(
        self, mock_bot_client, mock_user_client, mock_ai_service
    ):
        bot = AIBotService(mock_bot_client, mock_user_client, mock_ai_service, owner_id=7522968153)
        mock_ai_service.ask = AsyncMock(return_value=AIResponse(text="Here are your groceries"))

        event = MagicMock()
        event.chat_id = 7522968153
        event.raw_text = "Find my messages about groceries"
        event.is_private = True
        event.is_group = False
        event.is_channel = False
        event.sender_id = 7522968153  # Owner
        event.reply = AsyncMock()

        await bot._on_message(event)
        mock_ai_service.ask.assert_awaited_once()
        args, kwargs = mock_ai_service.ask.call_args
        assert args[0] == "Find my messages about groceries"
        assert kwargs["session_id"] == "7522968153"
        # Directly replies without sending an intermediate "thinking..." message
        event.reply.assert_awaited_once()
        assert "Here are your groceries" in event.reply.call_args[0][0]

    @pytest.mark.asyncio
    async def test_clear_session_command(
        self, mock_bot_client, mock_user_client, mock_ai_service
    ):
        bot = AIBotService(mock_bot_client, mock_user_client, mock_ai_service, owner_id=7522968153)
        event = MagicMock()
        event.chat_id = 7522968153
        event.raw_text = "/clear"
        event.is_private = True
        event.is_group = False
        event.is_channel = False
        event.sender_id = 7522968153
        event.reply = AsyncMock()

        await bot._on_message(event)
        mock_ai_service.clear_session_history.assert_called_once_with("7522968153")
        event.reply.assert_awaited_once()
        assert "cleared" in event.reply.call_args[0][0]

    @pytest.mark.asyncio
    async def test_group_message_ignored_when_not_mentioned(
        self, mock_bot_client, mock_user_client, mock_ai_service
    ):
        bot = AIBotService(mock_bot_client, mock_user_client, mock_ai_service, owner_id=7522968153)
        bot.bot_username = "mightypen_bot"

        event = MagicMock()
        event.raw_text = "Just talking in group"
        event.is_private = False
        event.is_group = True
        event.is_channel = False
        event.is_reply = False
        event.sender_id = 7522968153

        await bot._on_message(event)
        mock_ai_service.ask.assert_not_called()

    @pytest.mark.asyncio
    async def test_group_message_owner_mentioned(
        self, mock_bot_client, mock_user_client, mock_ai_service
    ):
        bot = AIBotService(mock_bot_client, mock_user_client, mock_ai_service, owner_id=7522968153)
        bot.bot_username = "mightypen_bot"

        chat = MagicMock()
        chat.title = "Project Group"

        event = MagicMock()
        event.chat_id = -1001234567
        event.raw_text = "@mightypen_bot summarize our tasks"
        event.is_private = False
        event.is_group = True
        event.is_channel = False
        event.is_reply = False
        event.sender_id = 7522968153  # Owner
        event.get_chat = AsyncMock(return_value=chat)
        event.reply = AsyncMock()

        await bot._on_message(event)
        mock_ai_service.ask.assert_awaited_once()
        args, kwargs = mock_ai_service.ask.call_args
        assert args[0] == "summarize our tasks"
        assert "Project Group" in kwargs["chat_context"]
        event.reply.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_callback_query_send_draft(
        self, mock_bot_client, mock_user_client, mock_ai_service
    ):
        bot = AIBotService(mock_bot_client, mock_user_client, mock_ai_service, owner_id=7522968153)
        event = MagicMock()
        event.sender_id = 7522968153
        event.data = b"send_draft:abc123"
        event.edit = AsyncMock()
        event.answer = AsyncMock()

        await bot._on_callback(event)
        mock_ai_service.confirm_draft.assert_awaited_once_with("abc123")
        event.edit.assert_awaited_once()
