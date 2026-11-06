"""Tests for app.cli – CLI dispatch, error handling, confirmation, and graceful shutdown."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.cli import CLI
from app.config import Config


@pytest.fixture
def mock_client():
    client = AsyncMock()
    me = MagicMock()
    me.id = 12345678
    me.first_name = "Test"
    me.last_name = "User"
    me.username = "testuser"
    client.get_me = AsyncMock(return_value=me)
    return client


@pytest.fixture
def cli(mock_client, tmp_path):
    cfg_file = tmp_path / "config.json"
    cfg = Config.load(cfg_file)
    return CLI(mock_client, cfg)


class TestCLIBasics:
    """Test basic CLI commands: help, me, quit."""

    async def test_help(self, cli, capsys):
        await cli._dispatch("help", [])
        captured = capsys.readouterr()
        assert "Available Commands" in captured.out
        assert "chats" in captured.out
        assert "reply" in captured.out
        assert "attach" in captured.out

    async def test_me(self, cli, capsys):
        await cli._dispatch("me", [])
        captured = capsys.readouterr()
        assert "Test User" in captured.out
        assert "@testuser" in captured.out
        assert "12345678" in captured.out

    async def test_quit(self, cli):
        assert cli._running is True
        await cli._dispatch("quit", [])
        assert cli._running is False

    async def test_exit(self, cli):
        assert cli._running is True
        await cli._dispatch("exit", [])
        assert cli._running is False

    async def test_unknown_command(self, cli, capsys):
        await cli._dispatch("foobar", [])
        captured = capsys.readouterr()
        assert "Unknown command: 'foobar'" in captured.out


class TestCLIChatRequirements:
    """Commands requiring an open chat should fail gracefully when no chat is open."""

    async def test_history_without_chat(self, cli):
        with pytest.raises(ValueError, match="No chat open"):
            await cli._dispatch("history", [])

    async def test_send_without_chat(self, cli):
        with pytest.raises(ValueError, match="No chat open"):
            await cli._dispatch("send", ["hello"])

    async def test_reply_without_chat(self, cli):
        with pytest.raises(ValueError, match="No chat open"):
            await cli._dispatch("reply", ["123", "hello"])

    async def test_attach_without_chat(self, cli):
        with pytest.raises(ValueError, match="No chat open"):
            await cli._dispatch("attach", ["file.txt"])

    async def test_attachments_without_chat(self, cli):
        with pytest.raises(ValueError, match="No chat open"):
            await cli._dispatch("attachments", [])

    async def test_download_without_chat(self, cli):
        with pytest.raises(ValueError, match="No chat open"):
            await cli._dispatch("download", ["123"])

    async def test_view_without_chat(self, cli):
        with pytest.raises(ValueError, match="No chat open"):
            await cli._dispatch("view", ["123"])


class TestCLIOpenAndSend:
    """Test opening a chat and sending messages / replies."""

    async def test_open_by_username(self, cli, capsys):
        entity = MagicMock()
        entity.title = "Target Group"
        entity.first_name = None
        entity.last_name = None
        entity.username = "targetgroup"
        entity.id = 999
        cli._client.get_entity = AsyncMock(return_value=entity)

        await cli._dispatch("open", ["@targetgroup"])
        assert cli._current_chat == entity
        assert cli._current_chat_name == "Target Group"
        captured = capsys.readouterr()
        assert "Opened: Target Group" in captured.out

    async def test_open_saved(self, cli, capsys):
        me_entity = MagicMock()
        me_entity.id = 12345
        cli._client.get_entity = AsyncMock(return_value=me_entity)
        cli._client.get_messages = AsyncMock(return_value=[])

        await cli._dispatch("open", ["saved"])
        assert cli._current_chat == me_entity
        assert cli._current_chat_name == "Saved Messages"
        captured = capsys.readouterr()
        assert "Opened: Saved Messages" in captured.out

    async def test_open_saved_messages(self, cli, capsys):
        me_entity = MagicMock()
        me_entity.id = 12345
        cli._client.get_entity = AsyncMock(return_value=me_entity)
        cli._client.get_messages = AsyncMock(return_value=[])

        await cli._dispatch("open", ["saved", "messages"])
        assert cli._current_chat == me_entity
        assert cli._current_chat_name == "Saved Messages"
        captured = capsys.readouterr()
        assert "Opened: Saved Messages" in captured.out

    async def test_saved_command(self, cli, capsys):
        me_entity = MagicMock()
        me_entity.id = 12345
        cli._client.get_entity = AsyncMock(return_value=me_entity)
        cli._client.get_messages = AsyncMock(return_value=[])

        await cli._dispatch("saved", [])
        assert cli._current_chat == me_entity
        assert cli._current_chat_name == "Saved Messages"
        captured = capsys.readouterr()
        assert "Opened: Saved Messages" in captured.out

    async def test_send_message(self, cli, capsys):
        cli._current_chat = MagicMock()
        cli._current_chat_name = "Test Chat"
        sent_msg = MagicMock()
        sent_msg.id = 55
        cli._client.send_message = AsyncMock(return_value=sent_msg)

        await cli._dispatch("send", ["Hello", "world!"])
        captured = capsys.readouterr()
        assert "Message sent (ID: 55)" in captured.out

    async def test_send_empty(self, cli, capsys):
        cli._current_chat = MagicMock()
        cli._current_chat_name = "Test Chat"
        await cli._dispatch("send", [])
        captured = capsys.readouterr()
        assert "Usage: send" in captured.out

    async def test_reply_message(self, cli, capsys):
        cli._current_chat = MagicMock()
        cli._current_chat_name = "Test Chat"
        # Mock get_messages for reply target validation
        target_msg = MagicMock()
        target_msg.id = 123
        cli._client.get_messages = AsyncMock(return_value=[target_msg])

        sent_msg = MagicMock()
        sent_msg.id = 56
        cli._client.send_message = AsyncMock(return_value=sent_msg)

        await cli._dispatch("reply", ["123", "Thanks!"])
        captured = capsys.readouterr()
        assert "Reply sent (ID: 56, replying to #123)" in captured.out

    async def test_reply_invalid_id(self, cli, capsys):
        cli._current_chat = MagicMock()
        cli._current_chat_name = "Test Chat"
        await cli._dispatch("reply", ["not_an_int", "Thanks!"])
        captured = capsys.readouterr()
        assert "MSG_ID must be a number" in captured.out


class TestCLIConfirmation:
    """Test send confirmation preference when enabled."""

    async def test_send_with_confirmation_yes(self, cli, capsys):
        cli._config.confirm_before_send = True
        cli._current_chat = MagicMock()
        cli._current_chat_name = "Test Chat"
        sent_msg = MagicMock()
        sent_msg.id = 88
        cli._client.send_message = AsyncMock(return_value=sent_msg)

        with patch("builtins.input", return_value="y"):
            await cli._dispatch("send", ["Hello"])

        captured = capsys.readouterr()
        assert "Message sent (ID: 88)" in captured.out

    async def test_send_with_confirmation_no(self, cli, capsys):
        cli._config.confirm_before_send = True
        cli._current_chat = MagicMock()
        cli._current_chat_name = "Test Chat"

        with patch("builtins.input", return_value="n"):
            await cli._dispatch("send", ["Hello"])

        captured = capsys.readouterr()
        assert "Cancelled" in captured.out
        cli._client.send_message.assert_not_called()


class TestCLISettingsCommands:
    """Test settings commands in CLI."""

    async def test_settings_list(self, cli, capsys):
        await cli._dispatch("settings", [])
        captured = capsys.readouterr()
        assert "Current settings:" in captured.out
        assert "download_dir" in captured.out
        assert "history_limit" in captured.out

    async def test_settings_set(self, cli, capsys):
        await cli._dispatch("settings", ["set", "history_limit", "45"])
        captured = capsys.readouterr()
        assert "changed" in captured.out
        assert cli._config.history_limit == 45

    async def test_settings_reset(self, cli, capsys):
        cli._config.history_limit = 45
        await cli._dispatch("settings", ["reset", "history_limit"])
        captured = capsys.readouterr()
        assert "reset to default" in captured.out
        assert cli._config.history_limit == 20


class TestCLIGracefulShutdown:
    """Test graceful shutdown of CLI run loop on EOFError or KeyboardInterrupt."""

    async def test_run_keyboard_interrupt(self, cli):
        with patch("builtins.input", side_effect=KeyboardInterrupt):
            await cli.run()
        # Should exit gracefully without raising uncaught exception

    async def test_run_eof_error(self, cli):
        with patch("builtins.input", side_effect=EOFError):
            await cli.run()
        # Should exit gracefully


class TestCLIAttach:
    """Test attach command in CLI."""

    async def test_attach_missing_args(self, cli, capsys):
        cli._current_chat = MagicMock()
        cli._current_chat_name = "Test Chat"
        await cli._dispatch("attach", [])
        captured = capsys.readouterr()
        assert "Usage: attach" in captured.out

    async def test_attach_success(self, cli, capsys, tmp_path):
        cli._current_chat = MagicMock()
        cli._current_chat_name = "Test Chat"
        f = tmp_path / "sample.pdf"
        f.write_text("test content")

        cli._media.upload_file = AsyncMock(return_value=101)

        await cli._dispatch("attach", [str(f)])
        captured = capsys.readouterr()
        assert "File sent (ID: 101)" in captured.out
        cli._media.upload_file.assert_called_once_with(
            cli._current_chat, str(f), caption=None, reply_to=None
        )

    async def test_attach_with_caption_and_reply(self, cli, capsys, tmp_path):
        cli._current_chat = MagicMock()
        cli._current_chat_name = "Test Chat"
        f = tmp_path / "sample.png"
        f.write_text("test image")

        cli._media.upload_file = AsyncMock(return_value=102)

        await cli._dispatch(
            "attach", [str(f), "--caption", "My image", "--reply", "77"]
        )
        captured = capsys.readouterr()
        assert "File sent (ID: 102)" in captured.out
        cli._media.upload_file.assert_called_once_with(
            cli._current_chat, str(f), caption="My image", reply_to=77
        )

    async def test_attach_with_confirmation_no(self, cli, capsys, tmp_path):
        cli._config.confirm_before_send = True
        cli._current_chat = MagicMock()
        cli._current_chat_name = "Test Chat"
        f = tmp_path / "sample.png"
        f.write_text("test image")

        cli._media.upload_file = AsyncMock()

        with patch("builtins.input", return_value="n"):
            await cli._dispatch("attach", [str(f)])

        captured = capsys.readouterr()
        assert "Cancelled" in captured.out
        cli._media.upload_file.assert_not_called()


class TestCLIAttachmentsAndDownload:
    """Test attachments, download, and view commands."""

    async def test_attachments_list(self, cli, capsys):
        cli._current_chat = MagicMock()
        cli._current_chat_name = "Test Chat"
        cli._media.get_attachments = AsyncMock(
            return_value=[
                {
                    "msg_id": 50,
                    "sender_name": "Alice",
                    "date": None,
                    "media_type": "photo",
                    "filename": "img.jpg",
                    "size": 1024,
                    "caption": "test",
                }
            ]
        )
        await cli._dispatch("attachments", ["10"])
        captured = capsys.readouterr()
        assert "[50]" in captured.out
        assert "Alice" in captured.out
        assert "[photo]" in captured.out

    async def test_attachments_empty(self, cli, capsys):
        cli._current_chat = MagicMock()
        cli._current_chat_name = "Test Chat"
        cli._media.get_attachments = AsyncMock(return_value=[])
        await cli._dispatch("attachments", [])
        captured = capsys.readouterr()
        assert "No attachments found" in captured.out

    async def test_download_success(self, cli, capsys, tmp_path):
        cli._current_chat = MagicMock()
        cli._current_chat_name = "Test Chat"
        fake_path = tmp_path / "dl.txt"
        cli._media.download_attachment = AsyncMock(return_value=fake_path)

        await cli._dispatch("download", ["50"])
        captured = capsys.readouterr()
        assert f"Downloaded: {fake_path}" in captured.out

    async def test_download_invalid_id(self, cli, capsys):
        cli._current_chat = MagicMock()
        cli._current_chat_name = "Test Chat"
        await cli._dispatch("download", ["abc"])
        captured = capsys.readouterr()
        assert "MSG_ID must be a number" in captured.out

    async def test_view_success(self, cli, capsys, tmp_path):
        cli._current_chat = MagicMock()
        cli._current_chat_name = "Test Chat"
        fake_path = tmp_path / "view.txt"
        cli._media.open_file = AsyncMock(return_value=fake_path)

        await cli._dispatch("view", ["50"])
        captured = capsys.readouterr()
        assert f"Opened: {fake_path}" in captured.out

    async def test_view_by_index_with_cached_attachments(self, cli, capsys, tmp_path):
        cli._current_chat = MagicMock()
        cli._current_chat_name = "Test Chat"
        fake_path = tmp_path / "view1.txt"
        cli._media.open_file = AsyncMock(return_value=fake_path)
        cli._last_attachments = [
            {"msg_id": 105063, "filename": "photo.jpg"},
            {"msg_id": 105064, "filename": "video.mp4"},
        ]

        await cli._dispatch("view", ["1"])
        cli._media.open_file.assert_called_once_with(cli._current_chat, 105063)
        captured = capsys.readouterr()
        assert f"Downloaded: {fake_path}" in captured.out
        assert f"Opened: {fake_path}" in captured.out

    async def test_view_by_index_without_cached_attachments(self, cli, capsys, tmp_path):
        cli._current_chat = MagicMock()
        cli._current_chat_name = "Test Chat"
        fake_path = tmp_path / "view2.txt"
        cli._media.open_file = AsyncMock(return_value=fake_path)
        cli._media.get_attachments = AsyncMock(
            return_value=[
                {"msg_id": 9999, "filename": "doc.pdf"},
            ]
        )

        await cli._dispatch("view", ["1"])
        cli._media.open_file.assert_called_once_with(cli._current_chat, 9999)
        captured = capsys.readouterr()
        assert f"Downloaded: {fake_path}" in captured.out
        assert f"Opened: {fake_path}" in captured.out

    async def test_download_by_index_with_cached_attachments(self, cli, capsys, tmp_path):
        cli._current_chat = MagicMock()
        cli._current_chat_name = "Test Chat"
        fake_path = tmp_path / "dl1.txt"
        cli._media.download_attachment = AsyncMock(return_value=fake_path)
        cli._last_attachments = [
            {"msg_id": 777, "filename": "photo.jpg"},
        ]

        await cli._dispatch("download", ["1"])
        cli._media.download_attachment.assert_called_once_with(cli._current_chat, 777)
        captured = capsys.readouterr()
        assert f"Downloaded: {fake_path}" in captured.out

    async def test_view_invalid_id(self, cli, capsys):
        cli._current_chat = MagicMock()
        cli._current_chat_name = "Test Chat"
        await cli._dispatch("view", ["abc"])
        captured = capsys.readouterr()
        assert "MSG_ID must be a number" in captured.out

    async def test_view_negative_id(self, cli, capsys):
        cli._current_chat = MagicMock()
        cli._current_chat_name = "Test Chat"
        await cli._dispatch("view", ["-5"])
        captured = capsys.readouterr()
        assert "MSG_ID must be a positive number" in captured.out

    async def test_download_negative_id(self, cli, capsys):
        cli._current_chat = MagicMock()
        cli._current_chat_name = "Test Chat"
        await cli._dispatch("download", ["0"])
        captured = capsys.readouterr()
        assert "MSG_ID must be a positive number" in captured.out


class TestCLIPrivacyAndNotifications:
    """Test account privacy and notification settings commands."""

    async def test_privacy_list(self, cli, capsys):
        cli._settings.get_privacy_settings = AsyncMock(
            return_value={"phone_number": "nobody", "last_seen": "contacts"}
        )
        await cli._dispatch("privacy", [])
        captured = capsys.readouterr()
        assert "Privacy settings:" in captured.out
        assert "phone_number: nobody" in captured.out

    async def test_privacy_set_confirmed(self, cli, capsys):
        cli._settings.update_privacy = AsyncMock(
            return_value="Privacy 'phone_number' updated to 'nobody'."
        )
        with patch("builtins.input", return_value="y"):
            await cli._dispatch("privacy", ["set", "phone_number", "nobody"])

        captured = capsys.readouterr()
        assert "Privacy 'phone_number' updated to 'nobody'." in captured.out

    async def test_privacy_set_cancelled(self, cli, capsys):
        cli._settings.update_privacy = AsyncMock()
        with patch("builtins.input", return_value="n"):
            await cli._dispatch("privacy", ["set", "phone_number", "nobody"])

        captured = capsys.readouterr()
        assert "Cancelled" in captured.out
        cli._settings.update_privacy.assert_not_called()

    async def test_notifications_list(self, cli, capsys):
        cli._settings.get_notify_settings = AsyncMock(
            return_value={"users": "enabled", "chats": "muted indefinitely"}
        )
        await cli._dispatch("notifications", [])
        captured = capsys.readouterr()
        assert "Notification settings:" in captured.out
        assert "users: enabled" in captured.out

    async def test_notifications_mute_confirmed(self, cli, capsys):
        cli._settings.update_notify_settings = AsyncMock(
            return_value="Notifications for users muted indefinitely."
        )
        with patch("builtins.input", return_value="y"):
            await cli._dispatch("notifications", ["mute", "users"])

        captured = capsys.readouterr()
        assert "Notifications for users muted indefinitely." in captured.out

    async def test_notifications_unmute(self, cli, capsys):
        cli._settings.update_notify_settings = AsyncMock(
            return_value="Notifications for users unmuted."
        )
        await cli._dispatch("notifications", ["unmute", "users"])
        captured = capsys.readouterr()
        assert "Notifications for users unmuted." in captured.out


class TestCLIErrorHandling:
    """Test error handling in CLI command loop."""

    async def test_flood_wait_handled(self, cli, capsys):
        from telethon.errors import FloodWaitError

        cli._current_chat = MagicMock()
        cli._messaging.send_message = AsyncMock(
            side_effect=FloodWaitError(request=None, capture=0)
        )
        # Set seconds attribute on FloodWaitError instance
        exc = FloodWaitError(request=None, capture=0)
        exc.seconds = 42

        # Simulate exception raised through CLI dispatch
        with patch.object(cli._messaging, "send_message", side_effect=exc):
            with patch("builtins.input", side_effect=["send hello", "quit"]):
                await cli.run()

        captured = capsys.readouterr()
        assert "Telegram rate limit: wait 42 seconds." in captured.out

    async def test_value_error_handled(self, cli, capsys):
        cli._current_chat = MagicMock()
        cli._messaging.send_message = AsyncMock(
            side_effect=ValueError("Invalid message ID")
        )

        with patch("builtins.input", side_effect=["send hello", "quit"]):
            await cli.run()

        captured = capsys.readouterr()
        assert "Error: Invalid message ID" in captured.out

    async def test_file_not_found_handled(self, cli, capsys):
        cli._current_chat = MagicMock()
        cli._media.upload_file = AsyncMock(
            side_effect=FileNotFoundError("File not found: missing.txt")
        )

        with patch("builtins.input", side_effect=['attach "missing.txt"', "quit"]):
            await cli.run()

        captured = capsys.readouterr()
        assert "File error: File not found: missing.txt" in captured.out


class TestCLILogout:
    """Test logout command in CLI."""

    async def test_logout_cancelled(self, cli, capsys):
        with patch("builtins.input", return_value="n"):
            await cli._dispatch("logout", [])
        captured = capsys.readouterr()
        assert "Cancelled" in captured.out

    async def test_logout_confirmed_file_deleted(self, cli, capsys):
        with patch("app.credentials.clear_credentials", return_value=True):
            with patch("builtins.input", return_value="y"):
                await cli._dispatch("logout", [])
        captured = capsys.readouterr()
        assert "Saved credentials removed" in captured.out

    async def test_logout_confirmed_no_file(self, cli, capsys):
        with patch("app.credentials.clear_credentials", return_value=False):
            with patch("builtins.input", return_value="y"):
                await cli._dispatch("logout", [])
        captured = capsys.readouterr()
        assert "No saved credentials file was found" in captured.out


class TestCLIChatsAndFolders:
    """Test folder listing, switching, and opening chats."""

    async def test_chats_shows_folders(self, cli, capsys):
        from app.services.messaging import FolderInfo
        f1 = FolderInfo(id=0, name="All chats", is_default=True)
        f2 = FolderInfo(id=2, name="Work", emoticon="💼")
        f3 = FolderInfo(id=1, name="Archived", is_archived=True)
        cli._messaging.get_folders = AsyncMock(return_value=[f1, f2, f3])

        await cli._dispatch("chats", [])
        captured = capsys.readouterr()
        assert "Chat Folders:" in captured.out
        assert "All chats (All conversations)" in captured.out
        assert "💼 Work" in captured.out
        assert "Archived (Archived chats)" in captured.out
        assert cli._view_mode == "folders"

    async def test_chats_all(self, cli, capsys):
        d1 = MagicMock()
        d1.name = "Alice"
        d1.id = 101
        d1.unread_count = 1
        cli._messaging.get_dialogs = AsyncMock(return_value=[d1])

        await cli._dispatch("chats", ["all"])
        captured = capsys.readouterr()
        assert "All Chats (1):" in captured.out
        assert "* Alice" in captured.out
        assert cli._view_mode == "chats"

    async def test_all_chats_dispatch(self, cli, capsys):
        d1 = MagicMock()
        d1.name = "Bob"
        d1.id = 102
        d1.unread_count = 0
        cli._messaging.get_dialogs = AsyncMock(return_value=[d1])

        await cli._dispatch("all", ["chats"])
        captured = capsys.readouterr()
        assert "All Chats (1):" in captured.out
        assert "Bob" in captured.out

    async def test_open_folder_by_index_in_folder_mode(self, cli, capsys):
        from app.services.messaging import FolderInfo
        f1 = FolderInfo(id=0, name="All chats", is_default=True)
        f2 = FolderInfo(id=2, name="Work")
        cli._messaging._folders = [f1, f2]
        cli._view_mode = "folders"

        d1 = MagicMock()
        d1.name = "Work Chat"
        d1.id = 201
        d1.unread_count = 0
        cli._messaging.get_folder_dialogs = AsyncMock(return_value=[d1])

        await cli._dispatch("open", ["2"])
        captured = capsys.readouterr()
        assert "Chats in 'Work' (1):" in captured.out
        assert "Work Chat" in captured.out
        assert cli._view_mode == "chats"

    async def test_open_folder_by_name(self, cli, capsys):
        from app.services.messaging import FolderInfo
        f1 = FolderInfo(id=0, name="All chats", is_default=True)
        f2 = FolderInfo(id=2, name="Work")
        cli._messaging._folders = [f1, f2]

        d1 = MagicMock()
        d1.name = "Work Chat"
        d1.id = 201
        d1.unread_count = 0
        cli._messaging.get_folder_dialogs = AsyncMock(return_value=[d1])

        await cli._dispatch("open", ["Work"])
        captured = capsys.readouterr()
        assert "Chats in 'Work' (1):" in captured.out

    async def test_open_chat_in_chat_mode(self, cli, capsys):
        cli._view_mode = "chats"
        entity = MagicMock()
        entity.title = "Target Chat"
        cli._messaging.open_chat = AsyncMock(return_value=(entity, "Target Chat"))

        await cli._dispatch("open", ["1"])
        captured = capsys.readouterr()
        assert "Opened: Target Chat" in captured.out
        assert cli._current_chat == entity


class TestCLIChannelsAndArchived:
    """Test channels and archived commands."""

    async def test_channels_command(self, cli, capsys):
        ch1 = MagicMock()
        ch1.name = "Python News"
        ch1.id = -1001
        ch1.unread_count = 2
        cli._messaging.get_channels = AsyncMock(return_value=[ch1])

        await cli._dispatch("channels", [])
        captured = capsys.readouterr()
        assert "Channels (1):" in captured.out
        assert "* Python News" in captured.out
        assert cli._view_mode == "chats"

    async def test_channels_empty(self, cli, capsys):
        cli._messaging.get_channels = AsyncMock(return_value=[])

        await cli._dispatch("channels", [])
        captured = capsys.readouterr()
        assert "No channels found." in captured.out

    async def test_archived_command(self, cli, capsys):
        d1 = MagicMock()
        d1.name = "Archived Group"
        d1.id = -1002
        d1.unread_count = 0
        cli._messaging.get_archived_dialogs = AsyncMock(return_value=[d1])

        await cli._dispatch("archived", [])
        captured = capsys.readouterr()
        assert "Archived Chats (1):" in captured.out
        assert "Archived Group" in captured.out
        assert cli._view_mode == "chats"

    async def test_archived_empty(self, cli, capsys):
        cli._messaging.get_archived_dialogs = AsyncMock(return_value=[])

        await cli._dispatch("archived", [])
        captured = capsys.readouterr()
        assert "No archived conversations found." in captured.out


class TestCLIMassArchiveAndUnarchive:
    """Test archive and unarchive commands."""

    async def test_archive_success(self, cli, capsys):
        cli._messaging.archive_chats = AsyncMock(return_value=["Alice", "Bob"])

        await cli._dispatch("archive", ["1", "2"])
        captured = capsys.readouterr()
        assert "Archived 2 chat(s): Alice, Bob" in captured.out
        cli._messaging.archive_chats.assert_called_once_with(["1", "2"])

    async def test_archive_missing_args(self, cli, capsys):
        await cli._dispatch("archive", [])
        captured = capsys.readouterr()
        assert "Usage: archive" in captured.out

    async def test_unarchive_success(self, cli, capsys):
        cli._messaging.unarchive_chats = AsyncMock(return_value=["Alice"])

        await cli._dispatch("unarchive", ["1"])
        captured = capsys.readouterr()
        assert "Unarchived 1 chat(s): Alice" in captured.out
        cli._messaging.unarchive_chats.assert_called_once_with(["1"])

    async def test_unarchive_missing_args(self, cli, capsys):
        await cli._dispatch("unarchive", [])
        captured = capsys.readouterr()
        assert "Usage: unarchive" in captured.out


class TestCLIFolderCommand:
    """Test folder command with subcommands."""

    async def test_folder_list(self, cli, capsys):
        from app.services.messaging import FolderInfo
        f1 = FolderInfo(id=0, name="All chats", is_default=True)
        cli._messaging.get_folders = AsyncMock(return_value=[f1])

        await cli._dispatch("folder", [])
        captured = capsys.readouterr()
        assert "Chat Folders:" in captured.out

    async def test_folder_add_success(self, cli, capsys):
        cli._messaging.add_to_folder = AsyncMock(
            return_value=("Work", ["Alice", "Bob"])
        )

        await cli._dispatch("folder", ["add", "Work", "1", "2"])
        captured = capsys.readouterr()
        assert "Added 2 chat(s) to 'Work': Alice, Bob" in captured.out

    async def test_folder_add_missing_args(self, cli, capsys):
        await cli._dispatch("folder", ["add", "Work"])
        captured = capsys.readouterr()
        assert "Usage: folder add" in captured.out

    async def test_folder_remove_success(self, cli, capsys):
        cli._messaging.remove_from_folder = AsyncMock(
            return_value=("Work", ["Alice"])
        )

        await cli._dispatch("folder", ["remove", "Work", "1"])
        captured = capsys.readouterr()
        assert "Removed 1 chat(s) from 'Work': Alice" in captured.out

    async def test_folder_remove_missing_args(self, cli, capsys):
        await cli._dispatch("folder", ["remove"])
        captured = capsys.readouterr()
        assert "Usage: folder remove" in captured.out


class TestCLIRealtimeChatting:
    """Test real-time message receiving for open chats."""

    async def test_on_new_message_no_chat_open(self, cli, capsys):
        event = MagicMock()
        event.out = False
        event.chat_id = 12345
        await cli._on_new_message(event)
        captured = capsys.readouterr()
        assert captured.out == ""

    async def test_on_new_message_outgoing_ignored(self, cli, capsys):
        chat = MagicMock()
        chat.id = 12345
        cli._current_chat = chat
        cli._current_chat_name = "Alice"

        event = MagicMock()
        event.out = True
        event.chat_id = 12345
        await cli._on_new_message(event)
        captured = capsys.readouterr()
        assert captured.out == ""

    async def test_on_new_message_different_chat_ignored(self, cli, capsys):
        chat = MagicMock()
        chat.id = 12345
        cli._current_chat = chat
        cli._current_chat_name = "Alice"

        event = MagicMock()
        event.out = False
        event.chat_id = 99999
        await cli._on_new_message(event)
        captured = capsys.readouterr()
        assert captured.out == ""

    async def test_on_new_message_matching_chat_displayed(self, cli, capsys):
        from telethon.tl import types
        chat = types.User(id=12345)
        cli._current_chat = chat
        cli._current_chat_name = "Alice"

        event = MagicMock()
        event.out = False
        event.chat_id = 12345
        event.message = MagicMock()
        event.message.id = 77
        event.message.message = "Hello in real time!"
        event.message.date = None
        event.message.reply_to = None
        event.message.media = None
        sender = MagicMock()
        sender.title = None
        sender.first_name = "Alice"
        sender.last_name = None
        sender.username = None
        event.message.get_sender = AsyncMock(return_value=sender)

        await cli._on_new_message(event)
        captured = capsys.readouterr()
        assert "[77] Alice (??:??): Hello in real time!" in captured.out

    async def test_close_command(self, cli, capsys):
        cli._current_chat = MagicMock()
        cli._current_chat_name = "Alice"

        await cli._dispatch("close", [])
        captured = capsys.readouterr()
        assert "Closed chat: Alice" in captured.out
        assert cli._current_chat is None
        assert cli._current_chat_name == ""

    async def test_close_command_when_no_chat(self, cli, capsys):
        cli._current_chat = None
        await cli._dispatch("close", [])
        captured = capsys.readouterr()
        assert "No chat is currently open." in captured.out
