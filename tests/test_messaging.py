"""Tests for app.services.messaging – message formatting, parsing, and validation."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.messaging import MessagingService


class TestFormatMessage:
    """Test message formatting for terminal display."""

    def _make_msg(self, **overrides) -> dict:
        base = {
            "id": 100,
            "sender_name": "Alice",
            "text": "Hello, world!",
            "date": datetime(2025, 6, 15, 14, 32, tzinfo=timezone.utc),
            "reply_to_msg_id": None,
            "has_media": False,
            "media_type": None,
        }
        base.update(overrides)
        return base

    def test_basic_message(self):
        msg = self._make_msg()
        result = MessagingService.format_message(msg)
        assert "[100]" in result
        assert "Alice" in result
        assert "14:32" in result
        assert "Hello, world!" in result

    def test_message_with_reply(self):
        msg = self._make_msg(id=101, reply_to_msg_id=100)
        result = MessagingService.format_message(msg)
        assert "↩" in result
        assert "#100" in result

    def test_message_with_media(self):
        msg = self._make_msg(has_media=True, media_type="photo", text="Check this")
        result = MessagingService.format_message(msg)
        assert "[photo]" in result
        assert "Check this" in result

    def test_message_no_text(self):
        msg = self._make_msg(text="", has_media=True, media_type="document")
        result = MessagingService.format_message(msg)
        assert "(no text)" in result
        assert "[document]" in result

    def test_message_with_media_and_reply(self):
        msg = self._make_msg(
            id=200,
            has_media=True,
            media_type="video",
            reply_to_msg_id=199,
            text="See this",
        )
        result = MessagingService.format_message(msg)
        assert "[200]" in result
        assert "↩" in result
        assert "#199" in result
        assert "[video]" in result
        assert "See this" in result


class TestDisplayName:
    """Test entity display name extraction."""

    def test_with_title(self):
        entity = MagicMock()
        entity.title = "My Group"
        entity.first_name = None
        entity.last_name = None
        entity.username = None
        entity.id = 123
        assert MessagingService.display_name_for_entity(entity) == "My Group"

    def test_with_first_and_last_name(self):
        entity = MagicMock()
        entity.title = None
        entity.first_name = "Bob"
        entity.last_name = "Smith"
        entity.username = "bob123"
        entity.id = 456
        assert MessagingService.display_name_for_entity(entity) == "Bob Smith"

    def test_with_first_name_only(self):
        entity = MagicMock()
        entity.title = None
        entity.first_name = "Bob"
        entity.last_name = None
        entity.username = "bob123"
        entity.id = 456
        assert MessagingService.display_name_for_entity(entity) == "Bob"

    def test_with_username_only(self):
        entity = MagicMock()
        entity.title = None
        entity.first_name = None
        entity.last_name = None
        entity.username = "anon_user"
        entity.id = 789
        assert MessagingService.display_name_for_entity(entity) == "anon_user"

    def test_with_id_only(self):
        entity = MagicMock()
        entity.title = None
        entity.first_name = None
        entity.last_name = None
        entity.username = None
        entity.id = 999
        assert MessagingService.display_name_for_entity(entity) == "999"


class TestOpenChat:
    """Test chat opening by index and target."""

    @pytest.fixture
    def service(self):
        client = AsyncMock()
        return MessagingService(client)

    async def test_open_no_dialogs_raises(self, service):
        with pytest.raises(ValueError, match="No dialogs loaded"):
            await service.open_chat("1")

    async def test_open_invalid_index_raises(self, service):
        d1 = MagicMock()
        d1.entity = MagicMock()
        d1.entity.title = "Chat 1"
        d1.entity.first_name = None
        d1.entity.last_name = None
        d1.entity.username = None
        d1.entity.id = 1
        service._dialogs = [d1]

        with pytest.raises(ValueError, match="Invalid index"):
            await service.open_chat("5")

    async def test_open_valid_index(self, service):
        d1 = MagicMock()
        d1.entity = MagicMock()
        d1.entity.title = "Group Chat"
        d1.entity.first_name = None
        d1.entity.last_name = None
        d1.entity.username = None
        d1.entity.id = 1
        service._dialogs = [d1]

        entity, name = await service.open_chat("1")
        assert entity == d1.entity
        assert name == "Group Chat"


class TestSendMessageValidation:
    """Test message sending with reply validation."""

    @pytest.fixture
    def service(self):
        client = AsyncMock()
        return MessagingService(client)

    async def test_send_with_nonexistent_reply(self, service):
        """Replying to a non-existent message should raise ValueError."""
        entity = MagicMock()
        # get_messages returns None for the reply target
        service._client.get_messages = AsyncMock(return_value=[None])

        with pytest.raises(ValueError, match="not found"):
            await service.send_message(entity, "Hello", reply_to=99999)

    async def test_send_without_reply(self, service):
        """Sending without reply should work normally."""
        entity = MagicMock()
        sent_msg = MagicMock()
        sent_msg.id = 42
        service._client.send_message = AsyncMock(return_value=sent_msg)

        msg_id = await service.send_message(entity, "Hello")
        assert msg_id == 42


class TestMediaTypeDetection:
    """Test media type detection from Telethon objects."""

    def test_photo(self):
        from telethon.tl.types import MessageMediaPhoto
        media = MagicMock(spec=MessageMediaPhoto)
        media.__class__ = MessageMediaPhoto
        assert MessagingService._detect_media_type(media) == "photo"

    def test_contact(self):
        from telethon.tl.types import MessageMediaContact
        media = MagicMock(spec=MessageMediaContact)
        media.__class__ = MessageMediaContact
        assert MessagingService._detect_media_type(media) == "contact"

    def test_unknown_media(self):
        media = MagicMock()
        result = MessagingService._detect_media_type(media)
        assert result == "media"
