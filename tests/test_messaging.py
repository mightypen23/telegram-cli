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

    def test_with_is_self(self):
        entity = MagicMock()
        entity.is_self = True
        entity.first_name = "Self"
        assert MessagingService.display_name_for_entity(entity) == "Saved Messages"

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

    async def test_open_saved_messages(self, service):
        me_entity = MagicMock()
        me_entity.id = 12345
        service._client.get_entity = AsyncMock(return_value=me_entity)

        entity, name = await service.open_chat("saved")
        assert entity == me_entity
        assert name == "Saved Messages"

        entity2, name2 = await service.open_chat("saved messages")
        assert entity2 == me_entity
        assert name2 == "Saved Messages"

        entity3, name3 = await service.open_chat("me")
        assert entity3 == me_entity
        assert name3 == "Saved Messages"

    async def test_resolve_target_saved(self, service):
        me_entity = MagicMock()
        me_entity.id = 12345
        service._client.get_entity = AsyncMock(return_value=me_entity)

        entity, name = await service.resolve_target("saved")
        assert entity == me_entity
        assert name == "Saved Messages"


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


class TestParseChatTargets:
    """Test parse_chat_targets helper."""

    def test_individual_indices(self):
        from app.services.messaging import parse_chat_targets
        assert parse_chat_targets(["1", "2", "3"]) == ["1", "2", "3"]

    def test_comma_separated(self):
        from app.services.messaging import parse_chat_targets
        assert parse_chat_targets(["1,2,3"]) == ["1", "2", "3"]

    def test_ranges(self):
        from app.services.messaging import parse_chat_targets
        assert parse_chat_targets(["1-4"]) == ["1", "2", "3", "4"]

    def test_mixed(self):
        from app.services.messaging import parse_chat_targets
        assert parse_chat_targets(["1-3", "5", "@user", "-100123"]) == [
            "1", "2", "3", "5", "@user", "-100123"
        ]

    def test_all_keyword(self):
        from app.services.messaging import parse_chat_targets
        assert parse_chat_targets(["all"]) == ["all"]


class TestArchivedAndChannels:
    """Test get_archived_dialogs and get_channels."""

    @pytest.fixture
    def service(self):
        client = AsyncMock()
        return MessagingService(client)

    async def test_get_archived_dialogs(self, service):
        d1 = MagicMock()
        d1.id = 100
        service._client.get_dialogs = AsyncMock(return_value=[d1])

        result = await service.get_archived_dialogs(limit=25)
        assert result == [d1]
        service._client.get_dialogs.assert_called_once_with(limit=25, folder=1)
        assert service.dialogs == [d1]

    async def test_get_channels(self, service):
        # Channel 1: broadcast channel (is_channel=True, is_group=False)
        ch1 = MagicMock()
        ch1.id = -1001
        ch1.is_channel = True
        ch1.is_group = False

        # Channel 2: supergroup (is_channel=True, is_group=True) -> excluded
        grp = MagicMock()
        grp.id = -1002
        grp.is_channel = True
        grp.is_group = True

        # User: is_channel=False, is_group=False -> excluded
        usr = MagicMock()
        usr.id = 1003
        usr.is_channel = False
        usr.is_group = False

        # Channel 3: broadcast channel
        ch2 = MagicMock()
        ch2.id = -1004
        ch2.is_channel = True
        ch2.is_group = False

        service._client.get_dialogs = AsyncMock(return_value=[ch1, grp, usr, ch2])

        result = await service.get_channels(limit=10)
        assert result == [ch1, ch2]
        assert service.dialogs == [ch1, ch2]


class TestFolderManagement:
    """Test folder listing, finding, and resolving folder dialogs."""

    @pytest.fixture
    def service(self):
        client = AsyncMock()
        return MessagingService(client)

    async def test_get_folders_empty_custom(self, service):
        from telethon.tl import types
        service._client.side_effect = None
        # Return DialogFilters with no custom filters
        df_resp = MagicMock()
        df_resp.filters = [types.DialogFilterDefault()]
        service._client.return_value = df_resp

        folders = await service.get_folders()
        assert len(folders) == 2
        assert folders[0].name == "All chats"
        assert folders[0].is_default is True
        assert folders[1].name == "Archived"
        assert folders[1].is_archived is True

    async def test_get_folders_with_custom(self, service):
        from telethon.tl import types
        flt = types.DialogFilter(
            id=2,
            title="Work",
            pinned_peers=[],
            include_peers=[],
            exclude_peers=[],
            emoticon="💼",
        )
        df_resp = MagicMock()
        df_resp.filters = [types.DialogFilterDefault(), flt]
        service._client.return_value = df_resp

        folders = await service.get_folders()
        assert len(folders) == 3
        assert folders[0].name == "All chats"
        assert folders[1].name == "Work"
        assert folders[1].id == 2
        assert folders[1].emoticon == "💼"
        assert folders[2].name == "Archived"

    def test_find_folder(self, service):
        from app.services.messaging import FolderInfo
        service._folders = [
            FolderInfo(id=0, name="All chats", is_default=True),
            FolderInfo(id=2, name="Work"),
            FolderInfo(id=1, name="Archived", is_archived=True),
        ]

        # By index
        assert service.find_folder("1").name == "All chats"
        assert service.find_folder("2").name == "Work"
        assert service.find_folder("3").name == "Archived"

        # By name (case insensitive)
        assert service.find_folder("work").name == "Work"
        assert service.find_folder("archived").name == "Archived"
        assert service.find_folder("all chats").name == "All chats"

        with pytest.raises(ValueError, match="Invalid folder index"):
            service.find_folder("99")

        with pytest.raises(ValueError, match="not found"):
            service.find_folder("NonExistent")

    async def test_get_folder_dialogs_default(self, service):
        from app.services.messaging import FolderInfo
        folder = FolderInfo(id=0, name="All chats", is_default=True)
        d1 = MagicMock()
        service._client.get_dialogs = AsyncMock(return_value=[d1])

        res = await service.get_folder_dialogs(folder)
        assert res == [d1]
        service._client.get_dialogs.assert_called_once_with(limit=100, folder=0)

    async def test_get_folder_dialogs_archived(self, service):
        from app.services.messaging import FolderInfo
        folder = FolderInfo(id=1, name="Archived", is_archived=True)
        d1 = MagicMock()
        service._client.get_dialogs = AsyncMock(return_value=[d1])

        res = await service.get_folder_dialogs(folder)
        assert res == [d1]
        service._client.get_dialogs.assert_called_once_with(limit=100, folder=1)

    async def test_get_folder_dialogs_custom(self, service):
        from app.services.messaging import FolderInfo
        from telethon.tl import types

        p_pinned = types.InputPeerUser(user_id=111, access_hash=0)
        p_include = types.InputPeerChannel(channel_id=222, access_hash=0)
        p_exclude = types.InputPeerUser(user_id=333, access_hash=0)

        flt = types.DialogFilter(
            id=2,
            title="Projects",
            pinned_peers=[p_pinned],
            include_peers=[p_include],
            exclude_peers=[p_exclude],
            groups=True,
        )
        folder = FolderInfo(id=2, name="Projects", filter_obj=flt)

        d_pinned = MagicMock()
        d_pinned.id = 111
        d_pinned.archived = False

        from telethon import utils
        inc_id = utils.get_peer_id(p_include)
        d_include = MagicMock()
        d_include.id = inc_id
        d_include.archived = False

        d_grp = MagicMock()
        d_grp.id = -999
        d_grp.is_group = True
        d_grp.archived = False

        d_excluded = MagicMock()
        d_excluded.id = 333
        d_excluded.is_group = True
        d_excluded.archived = False

        service._client.get_dialogs = AsyncMock(
            return_value=[d_include, d_grp, d_pinned, d_excluded]
        )

        res = await service.get_folder_dialogs(folder)
        # Pinned dialog comes first, followed by included, followed by rule matched (d_grp)
        # d_excluded is in exclude_peers so omitted
        assert res[0] == d_pinned
        assert d_include in res
        assert d_grp in res
        assert d_excluded not in res


class TestMassArchiveAndUnarchive:
    """Test archive_chats and unarchive_chats."""

    @pytest.fixture
    def service(self):
        client = AsyncMock()
        return MessagingService(client)

    async def test_archive_by_indices(self, service):
        d1 = MagicMock()
        d1.name = "Chat 1"
        d1.entity = MagicMock()
        d2 = MagicMock()
        d2.name = "Chat 2"
        d2.entity = MagicMock()
        service._dialogs = [d1, d2]

        names = await service.archive_chats(["1", "2"])
        assert names == ["Chat 1", "Chat 2"]
        service._client.edit_folder.assert_called_once_with(
            [d1.entity, d2.entity], folder=1
        )

    async def test_archive_all(self, service):
        d1 = MagicMock()
        d1.name = "Chat 1"
        d1.entity = MagicMock()
        service._dialogs = [d1]

        names = await service.archive_chats(["all"])
        assert names == ["Chat 1"]
        service._client.edit_folder.assert_called_once_with([d1.entity], folder=1)

    async def test_unarchive_by_indices(self, service):
        d1 = MagicMock()
        d1.name = "Archived Chat"
        d1.entity = MagicMock()
        service._dialogs = [d1]

        names = await service.unarchive_chats(["1"])
        assert names == ["Archived Chat"]
        service._client.edit_folder.assert_called_once_with([d1.entity], folder=0)

    async def test_unarchive_all(self, service):
        names = await service.unarchive_chats(["all"])
        assert names == ["all archived chats"]
        service._client.edit_folder.assert_called_once_with(unpack=1)


class TestFolderAddAndRemove:
    """Test add_to_folder and remove_from_folder."""

    @pytest.fixture
    def service(self):
        client = AsyncMock()
        return MessagingService(client)

    async def test_add_to_custom_folder(self, service):
        from app.services.messaging import FolderInfo
        from telethon.tl import types

        p_init = types.InputPeerUser(user_id=10, access_hash=0)
        flt = types.DialogFilter(
            id=2,
            title="Dev",
            pinned_peers=[],
            include_peers=[p_init],
            exclude_peers=[],
        )
        service._folders = [
            FolderInfo(id=0, name="All chats", is_default=True),
            FolderInfo(id=2, name="Dev", filter_obj=flt),
        ]

        target_peer = types.InputPeerUser(user_id=20, access_hash=0)
        target_entity = MagicMock()
        target_entity.first_name = "Alice"
        target_entity.last_name = None
        target_entity.title = None
        target_entity.username = None
        target_entity.id = 20

        d1 = MagicMock()
        d1.entity = target_entity
        d1.name = "Alice"
        service._dialogs = [d1]

        service._client.get_input_entity = AsyncMock(return_value=target_peer)
        service._client.side_effect = None
        service._client.return_value = True

        folder_name, names = await service.add_to_folder("Dev", ["1"])
        assert folder_name == "Dev"
        assert names == ["Alice"]
        assert target_peer in flt.include_peers

    async def test_remove_from_custom_folder(self, service):
        from app.services.messaging import FolderInfo
        from telethon.tl import types

        p_keep = types.InputPeerUser(user_id=10, access_hash=0)
        p_remove = types.InputPeerUser(user_id=20, access_hash=0)

        flt = types.DialogFilter(
            id=2,
            title="Dev",
            pinned_peers=[],
            include_peers=[p_keep, p_remove],
            exclude_peers=[],
            groups=True,
        )
        service._folders = [
            FolderInfo(id=0, name="All chats", is_default=True),
            FolderInfo(id=2, name="Dev", filter_obj=flt),
        ]

        target_entity = MagicMock()
        target_entity.first_name = "Bob"
        target_entity.last_name = None
        target_entity.title = None
        target_entity.username = None
        target_entity.id = 20

        d1 = MagicMock()
        d1.entity = target_entity
        d1.name = "Bob"
        service._dialogs = [d1]

        service._client.get_input_entity = AsyncMock(return_value=p_remove)
        service._client.side_effect = None
        service._client.return_value = True

        folder_name, names = await service.remove_from_folder("Dev", ["1"])
        assert folder_name == "Dev"
        assert names == ["Bob"]
        assert p_remove not in flt.include_peers
        assert p_remove in flt.exclude_peers


class TestMessageToDict:
    """Test message_to_dict conversion helper."""

    @pytest.fixture
    def service(self):
        client = AsyncMock()
        return MessagingService(client)

    async def test_none_or_empty_message(self, service):
        from telethon.tl.types import MessageEmpty
        assert await service.message_to_dict(None) is None
        assert await service.message_to_dict(MessageEmpty(id=1, peer_id=None)) is None

    async def test_valid_message_with_sender(self, service):
        msg = MagicMock()
        msg.id = 123
        msg.message = "Hello test"
        msg.date = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)
        msg.reply_to = None
        msg.media = None
        sender = MagicMock()
        sender.title = None
        sender.first_name = "Alice"
        sender.last_name = "Wonder"
        sender.username = "alicew"
        msg.get_sender = AsyncMock(return_value=sender)

        d = await service.message_to_dict(msg)
        assert d is not None
        assert d["id"] == 123
        assert d["sender_name"] == "Alice Wonder"
        assert d["text"] == "Hello test"
        assert d["has_media"] is False

    async def test_channel_post_message(self, service):
        msg = MagicMock()
        msg.id = 456
        msg.message = "Breaking news"
        msg.date = datetime(2026, 11, 3, 12, 5, tzinfo=timezone.utc)
        msg.reply_to = None
        msg.media = None
        msg.post = True
        msg.get_sender = AsyncMock(return_value=None)

        d = await service.message_to_dict(msg)
        assert d is not None
        assert d["id"] == 456
        assert d["sender_name"] == "Channel"
        assert d["text"] == "Breaking news"
