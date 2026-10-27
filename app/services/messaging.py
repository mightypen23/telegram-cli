"""
Messaging service – message history, sending, replying, and message lookup.

All Telethon message-related API calls are concentrated here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.tl.types import (
    MessageEmpty,
    MessageMediaContact,
    MessageMediaDocument,
    MessageMediaGeo,
    MessageMediaGeoLive,
    MessageMediaPhoto,
)


class MessagingService:
    """High-level wrapper around Telethon message operations."""

    def __init__(self, client: TelegramClient) -> None:
        self._client = client
        self._dialogs: list[Any] = []

    # ------------------------------------------------------------------ #
    #  Dialogs
    # ------------------------------------------------------------------ #

    async def get_dialogs(self, limit: int = 50) -> list[Any]:
        """Fetch recent dialogs and cache them for index-based access."""
        self._dialogs = await self._client.get_dialogs(limit=limit)
        return self._dialogs

    @property
    def dialogs(self) -> list[Any]:
        return self._dialogs

    async def open_chat(
        self, target: str, dialogs: list[Any] | None = None
    ) -> tuple[Any, str]:
        """
        Open a chat by index (1-based) or by username / entity string.

        Returns (entity, display_name).
        Raises ValueError on invalid index or unresolvable target.
        """
        dl = dialogs if dialogs is not None else self._dialogs

        if target.isdigit():
            idx = int(target)
            if not dl:
                raise ValueError("No dialogs loaded. Run 'chats' first.")
            if not 1 <= idx <= len(dl):
                raise ValueError(
                    f"Invalid index {idx}. Must be 1–{len(dl)}."
                )
            entity = dl[idx - 1].entity
        else:
            try:
                entity = await self._client.get_entity(target)
            except Exception as exc:
                raise ValueError(f"Cannot resolve '{target}': {exc}") from exc

        name = self.display_name_for_entity(entity)
        return entity, name

    # ------------------------------------------------------------------ #
    #  History
    # ------------------------------------------------------------------ #

    async def get_history(self, entity: Any, limit: int = 20) -> list[dict]:
        """
        Fetch the *limit* most recent messages in *entity*.

        Returns a list of dicts (oldest first) with keys:
            id, sender_name, text, date, reply_to_msg_id, has_media, media_type
        """
        messages = await self._client.get_messages(entity, limit=limit)
        result: list[dict] = []
        for msg in reversed(messages):
            if isinstance(msg, MessageEmpty):
                continue

            sender = await msg.get_sender()
            sender_name = "Unknown"
            if sender:
                title = getattr(sender, "title", None)
                if title:
                    sender_name = title
                else:
                    first = getattr(sender, "first_name", None) or ""
                    last = getattr(sender, "last_name", None) or ""
                    full = f"{first} {last}".strip()
                    sender_name = full or getattr(sender, "username", None) or "Unknown"

            reply_to_id = None
            if getattr(msg, "reply_to", None):
                reply_to_id = getattr(msg.reply_to, "reply_to_msg_id", None)

            media = getattr(msg, "media", None)
            media_type = self._detect_media_type(media) if media else None

            result.append(
                {
                    "id": msg.id,
                    "sender_name": sender_name,
                    "text": msg.message or "",
                    "date": msg.date,
                    "reply_to_msg_id": reply_to_id,
                    "has_media": media is not None,
                    "media_type": media_type,
                }
            )
        return result

    # ------------------------------------------------------------------ #
    #  Sending
    # ------------------------------------------------------------------ #

    async def send_message(
        self,
        entity: Any,
        text: str,
        reply_to: int | None = None,
    ) -> int:
        """
        Send a text message, optionally replying to *reply_to* message ID.

        Validates reply target exists before sending.
        Returns the sent message's ID.
        """
        if reply_to is not None:
            target_msg = await self.get_message_by_id(entity, reply_to)
            if target_msg is None:
                raise ValueError(
                    f"Message #{reply_to} not found in this chat."
                )

        sent = await self._client.send_message(
            entity, text, reply_to=reply_to
        )
        return sent.id

    async def get_message_by_id(self, entity: Any, msg_id: int) -> Any:
        """Fetch a single message by ID; returns None if not found or empty."""
        msgs = await self._client.get_messages(entity, ids=msg_id)
        msg = msgs[0] if isinstance(msgs, list) else msgs
        if msg is None or isinstance(msg, MessageEmpty):
            return None
        return msg

    # ------------------------------------------------------------------ #
    #  Formatting
    # ------------------------------------------------------------------ #

    @staticmethod
    def format_message(msg: dict) -> str:
        """
        Format a message dict for terminal display.

        Examples:
            [1234] Alice (14:32): Hello!
            [1235] Bob (14:33) ↩ #1234: Thanks!
            [1236] Alice (14:34): [photo] Check this out
        """
        mid = msg["id"]
        name = msg["sender_name"]
        dt: datetime = msg["date"]
        time_str = dt.strftime("%H:%M") if dt else "??:??"
        text = msg["text"]

        parts: list[str] = [f"[{mid}] {name} ({time_str})"]

        if msg.get("reply_to_msg_id"):
            parts.append(f" ↩ #{msg['reply_to_msg_id']}")

        parts.append(": ")

        if msg.get("has_media"):
            mtype = msg.get("media_type", "media")
            parts.append(f"[{mtype}] ")

        parts.append(text if text else "(no text)")

        return "".join(parts)

    @staticmethod
    def display_name_for_entity(entity: Any) -> str:
        """Extract a human-readable name from a Telethon entity."""
        name = getattr(entity, "title", None)
        if not name:
            first = getattr(entity, "first_name", None) or ""
            last = getattr(entity, "last_name", None) or ""
            full = f"{first} {last}".strip()
            if full:
                name = full
        if not name:
            name = getattr(entity, "username", None)
        if not name:
            name = str(getattr(entity, "id", "Unknown"))
        return name

    # ------------------------------------------------------------------ #
    #  Helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _detect_media_type(media: Any) -> str:
        """Return a human-readable media type string."""
        if isinstance(media, MessageMediaPhoto):
            return "photo"
        if isinstance(media, MessageMediaDocument):
            doc = media.document
            if doc:
                mime = getattr(doc, "mime_type", "") or ""
                # Check attributes for more detail
                for attr in getattr(doc, "attributes", []):
                    cls_name = type(attr).__name__
                    if cls_name == "DocumentAttributeSticker":
                        return "sticker"
                    if cls_name == "DocumentAttributeAnimated":
                        return "animation"
                    if cls_name == "DocumentAttributeAudio":
                        if getattr(attr, "voice", False):
                            return "voice"
                        return "audio"
                    if cls_name == "DocumentAttributeVideo":
                        if getattr(attr, "round_message", False):
                            return "video_note"
                        return "video"
                if mime.startswith("image/"):
                    return "image"
                if mime.startswith("video/"):
                    return "video"
                if mime.startswith("audio/"):
                    return "audio"
            return "document"
        if isinstance(media, MessageMediaContact):
            return "contact"
        if isinstance(media, (MessageMediaGeo, MessageMediaGeoLive)):
            return "location"
        return "media"
