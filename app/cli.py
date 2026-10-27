"""
Interactive command-line interface for Telegram CLI.

Handles command parsing, interactive prompts, and terminal output.
All Telegram API calls are delegated to the service modules.
"""

from __future__ import annotations

import argparse
import shlex
from typing import Any

from telethon import TelegramClient
from telethon.errors import FloodWaitError

from app.config import Config
from app.services.media import MediaService
from app.services.messaging import MessagingService
from app.services.settings import SettingsService


HELP_TEXT = """\
Telegram CLI - Available Commands:

Messaging:
  chats                              List recent conversations
  open INDEX | @username             Open a chat from the list or by username
  history [COUNT]                    Show recent messages (default: from settings)
  send MESSAGE                       Send a message to the open chat
  reply MSG_ID MESSAGE               Reply to a specific message in the open chat

Media & Attachments:
  attach FILE [--caption TEXT]       Upload a file with optional caption/reply
         [--reply MSG_ID]            (paths with spaces must be quoted)
  attachments [COUNT]                List recent media in the open chat
  download MSG_ID                    Download an attachment by message ID
  view MSG_ID                        Download and open an attachment with xdg-open

Local Settings:
  settings                           Show all local settings
  settings set KEY VALUE             Change a setting (e.g. download_dir, history_limit)
  settings reset KEY                 Reset a setting to its default value

Telegram Account:
  me                                 Show your account summary
  account                            Show detailed account info
  privacy                            Show account privacy settings
  privacy set KEY VALUE              Update privacy (everyone | contacts | nobody)
  notifications                      Show notification settings
  notifications mute TYPE [HOURS]    Mute notifications (users|chats|channels)
  notifications unmute TYPE          Unmute notifications

General:
  help                               Show this help message
  logout                             Clear saved credentials from this device
  quit | exit                        Exit the application
"""


class CLI:
    """Interactive command-line interface."""

    def __init__(
        self,
        client: TelegramClient,
        config: Config,
    ) -> None:
        self._client = client
        self._config = config
        self._messaging = MessagingService(client)
        self._media = MediaService(client, config.get_download_path())
        self._settings = SettingsService(config)

        self._current_chat: Any = None
        self._current_chat_name: str = ""
        self._running = True

    # ------------------------------------------------------------------ #
    #  Main loop
    # ------------------------------------------------------------------ #

    async def run(self) -> None:
        """Run the interactive command loop."""
        print("Type 'help' to see commands.\n")

        while self._running:
            try:
                prompt = (
                    f"telegram [{self._current_chat_name}]> "
                    if self._current_chat_name
                    else "telegram> "
                )
                command = input(prompt).strip()
            except (EOFError, KeyboardInterrupt):
                print("\nExiting.")
                break

            if not command:
                continue

            try:
                parts = shlex.split(command)
            except ValueError as exc:
                print(f"Parse error: {exc}")
                continue

            action = parts[0].lower()
            args = parts[1:]

            try:
                await self._dispatch(action, args)
            except FloodWaitError as exc:
                print(f"Telegram rate limit: wait {exc.seconds} seconds.")
            except (ValueError, TypeError) as exc:
                print(f"Error: {exc}")
            except FileNotFoundError as exc:
                print(f"File error: {exc}")
            except PermissionError as exc:
                print(f"Permission error: {exc}")
            except Exception as exc:
                print(f"Error: {type(exc).__name__}: {exc}")

    # ------------------------------------------------------------------ #
    #  Command dispatch
    # ------------------------------------------------------------------ #

    async def _dispatch(self, action: str, args: list[str]) -> None:
        """Route a parsed command to its handler."""
        handlers = {
            "quit": self._cmd_quit,
            "exit": self._cmd_quit,
            "help": self._cmd_help,
            "me": self._cmd_me,
            "chats": self._cmd_chats,
            "open": self._cmd_open,
            "history": self._cmd_history,
            "send": self._cmd_send,
            "reply": self._cmd_reply,
            "attach": self._cmd_attach,
            "attachments": self._cmd_attachments,
            "download": self._cmd_download,
            "view": self._cmd_view,
            "settings": self._cmd_settings,
            "account": self._cmd_account,
            "privacy": self._cmd_privacy,
            "notifications": self._cmd_notifications,
            "logout": self._cmd_logout,
        }

        handler = handlers.get(action)
        if handler is None:
            print(f"Unknown command: '{action}'. Type 'help' for commands.")
            return

        await handler(args)

    # ------------------------------------------------------------------ #
    #  Command handlers
    # ------------------------------------------------------------------ #

    async def _cmd_quit(self, args: list[str]) -> None:
        self._running = False

    async def _cmd_help(self, args: list[str]) -> None:
        print(HELP_TEXT)

    async def _cmd_me(self, args: list[str]) -> None:
        me = await self._client.get_me()
        name = f"{me.first_name or ''} {me.last_name or ''}".strip()
        print(f"Name: {name}")
        print(f"Username: @{me.username}" if me.username else "")
        print(f"ID: {me.id}")

    async def _cmd_chats(self, args: list[str]) -> None:
        limit = 50
        if args and args[0].isdigit():
            limit = int(args[0])
        dialogs = await self._messaging.get_dialogs(limit=limit)
        if not dialogs:
            print("No conversations found.")
            return
        for idx, dialog in enumerate(dialogs, start=1):
            marker = "*" if dialog.unread_count else " "
            name = (
                dialog.name
                or getattr(dialog.entity, "username", None)
                or str(dialog.id)
            )
            print(f"{idx:>3}. {marker} {name} (ID: {dialog.id})")

    async def _cmd_open(self, args: list[str]) -> None:
        if not args:
            print("Usage: open INDEX  or  open @username")
            return
        target = " ".join(args)
        entity, name = await self._messaging.open_chat(target)
        self._current_chat = entity
        self._current_chat_name = name
        print(f"Opened: {name}")

    async def _cmd_history(self, args: list[str]) -> None:
        self._require_chat()
        limit = self._config.history_limit
        if args:
            try:
                limit = int(args[0])
            except ValueError:
                print("Count must be an integer.")
                return
            if not 1 <= limit <= 100:
                print("Count must be between 1 and 100.")
                return
        messages = await self._messaging.get_history(
            self._current_chat, limit=limit
        )
        if not messages:
            print("No messages found.")
            return
        for msg in messages:
            print(self._messaging.format_message(msg))

    async def _cmd_send(self, args: list[str]) -> None:
        self._require_chat()
        text = " ".join(args)
        if not text:
            print("Usage: send Your message here")
            return

        if self._config.confirm_before_send:
            try:
                confirm = input(f"Send to {self._current_chat_name}? [y/N] ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\nCancelled.")
                return
            if confirm not in ("y", "yes"):
                print("Cancelled.")
                return

        msg_id = await self._messaging.send_message(self._current_chat, text)
        print(f"Message sent (ID: {msg_id}).")

    async def _cmd_reply(self, args: list[str]) -> None:
        self._require_chat()
        if len(args) < 2:
            print("Usage: reply MSG_ID Your reply message")
            return

        try:
            reply_id = int(args[0])
        except ValueError:
            print("MSG_ID must be a number.")
            return

        text = " ".join(args[1:])
        if not text:
            print("Reply message cannot be empty.")
            return

        if self._config.confirm_before_send:
            try:
                confirm = input(
                    f"Reply to #{reply_id} in {self._current_chat_name}? [y/N] "
                ).strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\nCancelled.")
                return
            if confirm not in ("y", "yes"):
                print("Cancelled.")
                return

        msg_id = await self._messaging.send_message(
            self._current_chat, text, reply_to=reply_id
        )
        print(f"Reply sent (ID: {msg_id}, replying to #{reply_id}).")

    async def _cmd_attach(self, args: list[str]) -> None:
        self._require_chat()
        if not args:
            print('Usage: attach "/path/to/file" [--caption TEXT] [--reply MSG_ID]')
            return

        # Use argparse for robust flag and option handling
        parser = argparse.ArgumentParser(prog="attach", add_help=False)
        parser.add_argument("file_path", nargs="?", default=None)
        parser.add_argument("--caption", "-c", default=None)
        parser.add_argument("--reply", "-r", type=int, default=None)

        try:
            parsed = parser.parse_args(args)
        except (argparse.ArgumentError, SystemExit):
            print('Usage: attach "/path/to/file" [--caption TEXT] [--reply MSG_ID]')
            return

        if not parsed.file_path:
            print('Usage: attach "/path/to/file" [--caption TEXT] [--reply MSG_ID]')
            return

        if self._config.confirm_before_send:
            try:
                confirm = input(
                    f"Send file to {self._current_chat_name}? [y/N] "
                ).strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\nCancelled.")
                return
            if confirm not in ("y", "yes"):
                print("Cancelled.")
                return

        msg_id = await self._media.upload_file(
            self._current_chat,
            parsed.file_path,
            caption=parsed.caption,
            reply_to=parsed.reply,
        )
        print(f"File sent (ID: {msg_id}).")

    async def _cmd_attachments(self, args: list[str]) -> None:
        self._require_chat()
        limit = 30
        if args:
            try:
                limit = int(args[0])
            except ValueError:
                print("Count must be a number.")
                return
            if not 1 <= limit <= 100:
                print("Count must be between 1 and 100.")
                return

        attachments = await self._media.get_attachments(
            self._current_chat, limit=limit
        )
        if not attachments:
            print("No attachments found.")
            return
        for att in attachments:
            print(self._media.format_attachment(att))

    async def _cmd_download(self, args: list[str]) -> None:
        self._require_chat()
        if not args:
            print("Usage: download MSG_ID")
            return
        try:
            msg_id = int(args[0])
        except ValueError:
            print("MSG_ID must be a number.")
            return

        path = await self._media.download_attachment(
            self._current_chat, msg_id
        )
        print(f"Downloaded: {path}")

    async def _cmd_view(self, args: list[str]) -> None:
        self._require_chat()
        if not args:
            print("Usage: view MSG_ID")
            return
        try:
            msg_id = int(args[0])
        except ValueError:
            print("MSG_ID must be a number.")
            return

        path = await self._media.open_file(self._current_chat, msg_id)
        print(f"Opened: {path}")

    async def _cmd_settings(self, args: list[str]) -> None:
        if not args:
            settings = self._settings.list_settings()
            print("Current settings:")
            for key, value in settings.items():
                print(f"  {key}: {value!r}")
            print(f"\nValid keys: {', '.join(self._settings.get_valid_keys())}")
            return

        if args[0] == "set":
            if len(args) < 3:
                print("Usage: settings set KEY VALUE")
                return
            key = args[1]
            value = " ".join(args[2:])
            msg = self._settings.set_setting(key, value)
            print(msg)
            if key == "download_dir":
                self._media = MediaService(
                    self._client, self._config.get_download_path()
                )

        elif args[0] == "reset":
            if len(args) < 2:
                print("Usage: settings reset KEY")
                return
            key = args[1]
            msg = self._settings.reset_setting(key)
            print(msg)
            if key == "download_dir":
                self._media = MediaService(
                    self._client, self._config.get_download_path()
                )
        else:
            print("Usage: settings | settings set KEY VALUE | settings reset KEY")

    async def _cmd_account(self, args: list[str]) -> None:
        try:
            info = await self._settings.get_account_info(self._client)
            print("Telegram account:")
            for key, value in info.items():
                print(f"  {key}: {value}")
        except Exception as exc:
            print(f"Could not retrieve account info: {exc}")

    async def _cmd_privacy(self, args: list[str]) -> None:
        if not args:
            try:
                privacy = await self._settings.get_privacy_settings(self._client)
                print("Privacy settings:")
                for key, value in privacy.items():
                    print(f"  {key}: {value}")
            except Exception as exc:
                print(f"Could not retrieve privacy settings: {exc}")
            return

        if args[0] == "set":
            if len(args) < 3:
                print("Usage: privacy set SETTING VALUE")
                print("  Settings: phone_number, last_seen, profile_photo, forwards, group_invite, phone_call, phone_p2p")
                print("  Values:   everyone, contacts, nobody")
                return
            setting = args[1]
            value = args[2]

            try:
                confirm = input(
                    f"Change '{setting}' to '{value}'? This affects your Telegram account. [y/N] "
                ).strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\nCancelled.")
                return
            if confirm not in ("y", "yes"):
                print("Cancelled.")
                return

            msg = await self._settings.update_privacy(
                self._client, setting, value
            )
            print(msg)
        else:
            print("Usage: privacy | privacy set SETTING VALUE")

    async def _cmd_notifications(self, args: list[str]) -> None:
        if not args:
            try:
                notify = await self._settings.get_notify_settings(self._client)
                print("Notification settings:")
                for cat, status in notify.items():
                    print(f"  {cat}: {status}")
            except Exception as exc:
                print(f"Could not retrieve notification settings: {exc}")
            return

        subcmd = args[0].lower()
        if subcmd == "mute":
            if len(args) < 2:
                print("Usage: notifications mute users|chats|channels [HOURS]")
                return
            category = args[1].lower()
            hours = 0  # indefinite
            if len(args) >= 3:
                try:
                    hours = int(args[2])
                except ValueError:
                    print("HOURS must be an integer.")
                    return

            try:
                confirm = input(
                    f"Mute notifications for {category}? [y/N] "
                ).strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\nCancelled.")
                return
            if confirm not in ("y", "yes"):
                print("Cancelled.")
                return

            msg = await self._settings.update_notify_settings(
                self._client, category, hours
            )
            print(msg)

        elif subcmd == "unmute":
            if len(args) < 2:
                print("Usage: notifications unmute users|chats|channels")
                return
            category = args[1].lower()
            msg = await self._settings.update_notify_settings(
                self._client, category, None
            )
            print(msg)
        else:
            print("Usage: notifications | notifications mute TYPE [HOURS] | notifications unmute TYPE")

    async def _cmd_logout(self, args: list[str]) -> None:
        from app.credentials import clear_credentials

        try:
            confirm = input(
                "Clear saved Telegram API credentials from this device? [y/N] "
            ).strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nCancelled.")
            return

        if confirm not in ("y", "yes"):
            print("Cancelled.")
            return

        deleted = clear_credentials()
        if deleted:
            print("Saved credentials removed. You will be prompted on next launch.")
        else:
            print("No saved credentials file was found.")

    # ------------------------------------------------------------------ #
    #  Helpers
    # ------------------------------------------------------------------ #

    def _require_chat(self) -> None:
        """Raise ValueError if no chat is currently open."""
        if self._current_chat is None:
            raise ValueError("No chat open. Use 'open' to select a chat first.")
