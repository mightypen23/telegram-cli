"""
Interactive command-line interface for Telegram CLI.

Handles command parsing, interactive prompts, and terminal output.
All Telegram API calls are delegated to the service modules.
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import shlex
import sys
from typing import Any

from telethon import TelegramClient, events, utils
from telethon.errors import FloodWaitError

from app.config import Config
from app.services.ai import AIAssistantService
from app.services.bot import AIBotService
from app.services.media import MediaService
from app.services.messaging import MessagingService, parse_chat_targets
from app.services.settings import SettingsService


HELP_TEXT = """\
Telegram CLI - Available Commands:

AI Assistant:
  ai PROMPT...                       Ask the local AI assistant to manage chats, search, or draft
  bot [status|start|stop]            Manage the personal AI Telegram bot

Messaging:
  chats                              List chat folders
  all chats                          List all conversations
  channels [COUNT]                   List broadcast channels only
  archived [COUNT]                   List archived conversations
  open INDEX | FOLDER | @username    Open a chat from the list or by username
  saved                              Open Saved Messages
  close                              Close the currently open chat
  history [COUNT]                    Show recent messages (default: from settings)
  send MESSAGE                       Send a message to the open chat
  reply MSG_ID MESSAGE               Reply to a specific message in the open chat

Folders & Archiving:
  folder                             List chat folders
  folder add FOLDER CHATS...         Mass add chats to a folder (e.g. folder add Work 1 2 3)
  folder remove FOLDER CHATS...      Mass remove chats from a folder
  archive CHATS...                   Mass archive chats (e.g. archive 1 2 3, archive 1-5, all)
  unarchive CHATS...                 Mass unarchive chats (e.g. unarchive 1 2 3, all)

Media & Attachments:
  attach FILE [--caption TEXT]       Upload a file with optional caption/reply
         [--reply MSG_ID]            (paths with spaces must be quoted)
  attachments [COUNT]                List recent media in the open chat
  download INDEX | MSG_ID            Download an attachment by index or message ID
  view INDEX | MSG_ID                Download and open an attachment with xdg-open

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
        bot_service: AIBotService | None = None,
    ) -> None:
        self._client = client
        self._config = config
        self._messaging = MessagingService(client)
        self._media = MediaService(client, config.get_download_path())
        self._settings = SettingsService(config)
        self._ai = AIAssistantService(
            self._messaging,
            ollama_url=config.ollama_url,
            model=config.ai_model,
            draft_first=config.ai_draft_first,
        )
        self._bot = bot_service

        self._current_chat: Any = None
        self._current_chat_name: str = ""
        self._view_mode: str = "folders"
        self._last_attachments: list[dict] = []
        self._running = True

        if hasattr(self._client, "add_event_handler"):
            try:
                res = self._client.add_event_handler(
                    self._on_new_message, events.NewMessage
                )
                if inspect.iscoroutine(res):
                    res.close()
            except Exception:
                pass

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
                command = await self._async_input(prompt)
                command = command.strip()
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

    async def _async_input(self, prompt: str) -> str:
        """Read user input asynchronously so event handlers can run."""
        return await asyncio.to_thread(input, prompt)

    def _print_live_message(self, text: str) -> None:
        """Print an incoming message in real time without breaking prompt display."""
        prompt = (
            f"telegram [{self._current_chat_name}]> "
            if self._current_chat_name
            else "telegram> "
        )

        current_buffer = ""
        try:
            import readline
            current_buffer = readline.get_line_buffer() or ""
        except Exception:
            pass

        if sys.stdout.isatty():
            sys.stdout.write(f"\r\033[K{text}\n{prompt}{current_buffer}")
            sys.stdout.flush()
        else:
            print(text)

    async def _on_new_message(self, event: Any) -> None:
        """Handle incoming real-time messages for the open chat."""
        if not self._current_chat or getattr(event, "out", False):
            return

        chat_id = getattr(event, "chat_id", None)
        if chat_id is None:
            return

        try:
            current_chat_id = utils.get_peer_id(self._current_chat)
        except Exception:
            current_chat_id = getattr(self._current_chat, "id", None)

        if chat_id != current_chat_id:
            return

        message = getattr(event, "message", None)
        if not message:
            return

        msg_dict = await self._messaging.message_to_dict(message)
        if not msg_dict:
            return

        formatted = self._messaging.format_message(msg_dict)
        self._print_live_message(formatted)

    # ------------------------------------------------------------------ #
    #  Command dispatch
    # ------------------------------------------------------------------ #

    async def _dispatch(self, action: str, args: list[str]) -> None:
        """Route a parsed command to its handler."""
        if action in ("all", "all chats", "allchats", "all-chats"):
            if args and args[0].lower() in ("chats", "chat"):
                args = args[1:]
            await self._cmd_all_chats(args)
            return

        handlers = {
            "quit": self._cmd_quit,
            "exit": self._cmd_quit,
            "help": self._cmd_help,
            "me": self._cmd_me,
            "chats": self._cmd_chats,
            "all": self._cmd_all_chats,
            "channels": self._cmd_channels,
            "archived": self._cmd_archived,
            "archive": self._cmd_archive,
            "unarchive": self._cmd_unarchive,
            "folder": self._cmd_folder,
            "folders": self._cmd_folder,
            "open": self._cmd_open,
            "saved": self._cmd_saved,
            "close": self._cmd_close,
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
            "ai": self._cmd_ai,
            "bot": self._cmd_bot,
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
        if hasattr(self._client, "remove_event_handler"):
            try:
                res = self._client.remove_event_handler(
                    self._on_new_message, events.NewMessage
                )
                if inspect.iscoroutine(res):
                    res.close()
            except Exception:
                pass

    async def _cmd_close(self, args: list[str]) -> None:
        if self._current_chat is None:
            print("No chat is currently open.")
            return
        name = self._current_chat_name
        self._current_chat = None
        self._current_chat_name = ""
        self._last_attachments = []
        print(f"Closed chat: {name}")

    async def _cmd_saved(self, args: list[str]) -> None:
        await self._cmd_open(["saved"])

    async def _cmd_help(self, args: list[str]) -> None:
        print(HELP_TEXT)

    async def _cmd_me(self, args: list[str]) -> None:
        me = await self._client.get_me()
        name = f"{me.first_name or ''} {me.last_name or ''}".strip()
        print(f"Name: {name}")
        print(f"Username: @{me.username}" if me.username else "")
        print(f"ID: {me.id}")

    def _print_dialogs(self, dialogs: list[Any]) -> None:
        for idx, dialog in enumerate(dialogs, start=1):
            marker = "*" if getattr(dialog, "unread_count", 0) else " "
            name = (
                getattr(dialog, "name", None)
                or getattr(getattr(dialog, "entity", None), "username", None)
                or str(getattr(dialog, "id", "Unknown"))
            )
            print(f"{idx:>3}. {marker} {name} (ID: {getattr(dialog, 'id', '')})")

    async def _display_folders(self) -> None:
        folders = await self._messaging.get_folders()
        if not folders:
            print("No chat folders found.")
            return
        self._view_mode = "folders"
        print("Chat Folders:")
        for idx, f in enumerate(folders, start=1):
            tag = ""
            if f.is_default:
                tag = " (All conversations)"
            elif f.is_archived:
                tag = " (Archived chats)"
            emoji = f"{f.emoticon} " if f.emoticon else ""
            print(f"{idx:>3}. {emoji}{f.name}{tag}")
        print(
            "\nType 'open <folder>' or 'open <index>' to view chats in a folder (e.g. 'open 1' or 'open Work')."
        )
        print("Type 'all chats' to view all chats directly.")

    async def _cmd_chats(self, args: list[str]) -> None:
        if args and args[0].lower() in ("all", "--all"):
            await self._cmd_all_chats(args[1:])
            return
        await self._display_folders()

    async def _cmd_all_chats(self, args: list[str]) -> None:
        limit = 50
        if args and args[0].isdigit():
            limit = int(args[0])
        elif args and len(args) > 1 and args[1].isdigit():
            limit = int(args[1])
        dialogs = await self._messaging.get_dialogs(limit=limit, folder=0)
        if not dialogs:
            print("No conversations found.")
            return
        self._view_mode = "chats"
        print(f"All Chats ({len(dialogs)}):")
        self._print_dialogs(dialogs)

    async def _cmd_channels(self, args: list[str]) -> None:
        limit = 50
        if args and args[0].isdigit():
            limit = int(args[0])
        channels = await self._messaging.get_channels(limit=limit)
        if not channels:
            print("No channels found.")
            return
        self._view_mode = "chats"
        print(f"Channels ({len(channels)}):")
        self._print_dialogs(channels)

    async def _cmd_archived(self, args: list[str]) -> None:
        limit = 50
        if args and args[0].isdigit():
            limit = int(args[0])
        dialogs = await self._messaging.get_archived_dialogs(limit=limit)
        if not dialogs:
            print("No archived conversations found.")
            return
        self._view_mode = "chats"
        print(f"Archived Chats ({len(dialogs)}):")
        self._print_dialogs(dialogs)

    async def _cmd_archive(self, args: list[str]) -> None:
        if not args:
            print("Usage: archive INDEX... | @username... | all")
            return
        targets = parse_chat_targets(args)
        if not targets:
            print("Usage: archive INDEX... | @username... | all")
            return
        names = await self._messaging.archive_chats(targets)
        print(f"Archived {len(names)} chat(s): {', '.join(names)}")

    async def _cmd_unarchive(self, args: list[str]) -> None:
        if not args:
            print("Usage: unarchive INDEX... | @username... | all")
            return
        targets = parse_chat_targets(args)
        if not targets:
            print("Usage: unarchive INDEX... | @username... | all")
            return
        names = await self._messaging.unarchive_chats(targets)
        print(f"Unarchived {len(names)} chat(s): {', '.join(names)}")

    async def _cmd_folder(self, args: list[str]) -> None:
        if not args or args[0].lower() in ("list", "show"):
            await self._display_folders()
            return

        subcmd = args[0].lower()
        if subcmd == "add":
            if len(args) < 3:
                print("Usage: folder add FOLDER_NAME_OR_INDEX CHATS...")
                return
            folder_target = args[1]
            chat_targets = parse_chat_targets(args[2:])
            folder_name, names = await self._messaging.add_to_folder(
                folder_target, chat_targets
            )
            print(
                f"Added {len(names)} chat(s) to '{folder_name}': {', '.join(names)}"
            )

        elif subcmd == "remove":
            if len(args) < 3:
                print("Usage: folder remove FOLDER_NAME_OR_INDEX CHATS...")
                return
            folder_target = args[1]
            chat_targets = parse_chat_targets(args[2:])
            folder_name, names = await self._messaging.remove_from_folder(
                folder_target, chat_targets
            )
            print(
                f"Removed {len(names)} chat(s) from '{folder_name}': {', '.join(names)}"
            )

        else:
            print(
                "Usage: folder | folder list | folder add FOLDER CHATS... | folder remove FOLDER CHATS..."
            )

    async def _open_folder(self, folder_target: str) -> None:
        folder = self._messaging.find_folder(folder_target)
        if folder.is_default:
            await self._cmd_all_chats([])
            return
        if folder.is_archived:
            await self._cmd_archived([])
            return

        dialogs = await self._messaging.get_folder_dialogs(folder)
        if not dialogs:
            print(f"No chats found in folder '{folder.name}'.")
            return
        self._view_mode = "chats"
        print(f"Chats in '{folder.name}' ({len(dialogs)}):")
        self._print_dialogs(dialogs)

    async def _cmd_open(self, args: list[str]) -> None:
        if not args:
            print("Usage: open INDEX | FOLDER | @username | saved")
            return

        target = " ".join(args).strip()
        target_lower = target.lower()

        if target_lower in ("saved", "saved messages", "saved_messages", "saved-messages", "me"):
            entity, name = await self._messaging.open_chat("saved")
            self._current_chat = entity
            self._current_chat_name = name
            self._view_mode = "chats"
            self._last_attachments = []
            print(f"Opened: {name}")
            await self._cmd_history([])
            return

        if target_lower in ("all chats", "all chat", "all"):
            await self._cmd_all_chats([])
            return

        if target_lower.startswith("folder "):
            folder_arg = target[7:].strip()
            await self._open_folder(folder_arg)
            return

        # If in folders mode and target is an integer: open that folder
        if (
            self._view_mode == "folders"
            and target.isdigit()
            and self._messaging.folders
        ):
            await self._open_folder(target)
            return

        # If target matches a known folder name: open that folder
        if self._messaging.folders:
            matched_folder = self._messaging.find_folder_by_name(target)
            if matched_folder is not None:
                await self._open_folder(matched_folder.name)
                return

        # Otherwise open chat
        entity, name = await self._messaging.open_chat(target)
        self._current_chat = entity
        self._current_chat_name = name
        self._view_mode = "chats"
        self._last_attachments = []
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

    async def _resolve_media_msg_id(self, val: int) -> int:
        """
        Resolve an attachment index (1-based) or message ID to a Telegram message ID.
        """
        if self._last_attachments and 1 <= val <= len(self._last_attachments):
            return self._last_attachments[val - 1]["msg_id"]

        if not self._last_attachments and self._current_chat is not None:
            try:
                atts = await self._media.get_attachments(self._current_chat, limit=30)
                if atts:
                    self._last_attachments = atts
                    if 1 <= val <= len(self._last_attachments):
                        return self._last_attachments[val - 1]["msg_id"]
            except Exception:
                pass

        return val

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
        self._last_attachments = attachments
        for idx, att in enumerate(attachments, start=1):
            print(f"{idx:>3}. {self._media.format_attachment(att)}")

    async def _cmd_download(self, args: list[str]) -> None:
        self._require_chat()
        if not args:
            print("Usage: download INDEX | MSG_ID")
            return
        try:
            val = int(args[0])
        except ValueError:
            print("MSG_ID must be a number.")
            return
        if val <= 0:
            print("MSG_ID must be a positive number.")
            return

        msg_id = await self._resolve_media_msg_id(val)
        path = await self._media.download_attachment(
            self._current_chat, msg_id
        )
        print(f"Downloaded: {path}")

    async def _cmd_view(self, args: list[str]) -> None:
        self._require_chat()
        if not args:
            print("Usage: view INDEX | MSG_ID")
            return
        try:
            val = int(args[0])
        except ValueError:
            print("MSG_ID must be a number.")
            return
        if val <= 0:
            print("MSG_ID must be a positive number.")
            return

        msg_id = await self._resolve_media_msg_id(val)
        path = await self._media.open_file(self._current_chat, msg_id)
        print(f"Downloaded: {path}")
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

    async def _cmd_ai(self, args: list[str]) -> None:
        """Query the local AI assistant to search chats, draft messages, etc."""
        if args and args[0].lower() in ("clear", "reset"):
            self._ai.clear_session_history("cli")
            print("AI conversation memory cleared.")
            return

        if not args:
            prompt = await self._async_input("AI prompt: ")
            prompt = prompt.strip()
            if not prompt:
                return
        else:
            prompt = " ".join(args)

        print(f"Thinking with {self._config.ai_model}...")
        chat_context = f"Open chat: {self._current_chat_name}" if self._current_chat_name else None
        response = await self._ai.ask(
            prompt,
            chat_context=chat_context,
            session_id="cli",
        )

        if response.draft:
            print("\n📝 Message Draft:")
            print(f"  To: {response.draft.recipient}")
            print(f"  Message: {response.draft.message}")
            try:
                confirm = (await self._async_input("\nSend this message? [y/N]: ")).strip().lower()
            except (EOFError, KeyboardInterrupt):
                confirm = "n"
            if confirm in ("y", "yes"):
                success, msg = await self._ai.confirm_draft(response.draft.id)
                print(msg)
            else:
                self._ai.cancel_draft(response.draft.id)
                print("Draft cancelled.")
        else:
            print(f"\n{response.text}\n")

    async def _cmd_bot(self, args: list[str]) -> None:
        """Manage the AI Telegram bot service."""
        sub = args[0].lower() if args else "status"

        if sub == "status":
            if self._bot and self._bot.is_running:
                print(f"AI Bot is ONLINE: @{self._bot.bot_username} (Model: {self._config.ai_model})")
            else:
                print("AI Bot is OFFLINE. Run 'bot start' to launch it.")

        elif sub == "start":
            from app.credentials import load_bot_token, load_credentials, save_bot_token

            if self._bot and self._bot.is_running:
                print(f"AI Bot is already running: @{self._bot.bot_username}")
                return

            token = load_bot_token()
            if not token:
                token = (await self._async_input("Telegram Bot Token (from @BotFather): ")).strip()
                if not token:
                    print("Bot token cannot be empty.")
                    return
                save_bot_token(token)

            creds = load_credentials()
            if not creds:
                print("User API credentials required.")
                return

            api_id, api_hash = creds
            bot_client = TelegramClient("bot_session", api_id, api_hash)
            self._bot = AIBotService(bot_client, self._client, self._ai)
            try:
                await self._bot.start(token)
                print(f"AI Bot started: @{self._bot.bot_username} (Owner: @{self._bot.owner_username})")
            except Exception as exc:
                print(f"Failed to start bot: {exc}")

        elif sub == "stop":
            if self._bot and self._bot.is_running:
                await self._bot.stop()
                print("AI Bot stopped.")
            else:
                print("AI Bot is not running.")
        else:
            print("Usage: bot [status|start|stop]")

    # ------------------------------------------------------------------ #
    #  Helpers
    # ------------------------------------------------------------------ #

    def _require_chat(self) -> None:
        """Raise ValueError if no chat is currently open."""
        if self._current_chat is None:
            raise ValueError("No chat open. Use 'open' to select a chat first.")
