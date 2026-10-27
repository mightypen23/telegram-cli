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
