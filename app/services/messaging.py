"""
Messaging service – message history, sending, replying, and message lookup.

All Telethon message-related API calls are concentrated here.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from telethon import TelegramClient, utils
from telethon.errors import FloodWaitError
from telethon.tl import functions, types
from telethon.tl.types import (
    MessageEmpty,
    MessageMediaContact,
    MessageMediaDocument,
    MessageMediaGeo,
    MessageMediaGeoLive,
    MessageMediaPhoto,
)


class FolderInfo:
    """Represents a Telegram chat folder (dialog filter) or virtual folder."""

    def __init__(
        self,
        id: int | None,
        name: str,
        filter_obj: Any = None,
        is_default: bool = False,
        is_archived: bool = False,
        emoticon: str | None = None,
    ) -> None:
        self.id = id
        self.name = name
        self.filter_obj = filter_obj
        self.is_default = is_default
        self.is_archived = is_archived
        self.emoticon = emoticon

    def __repr__(self) -> str:
        return (
            f"FolderInfo(id={self.id}, name={self.name!r}, "
            f"is_default={self.is_default}, is_archived={self.is_archived})"
        )


class PseudoDialog:
    """Fallback dialog wrapper for entities not present in recent dialogs."""

    def __init__(self, entity: Any) -> None:
        self.entity = entity
        try:
            self.id = utils.get_peer_id(entity)
        except Exception:
            self.id = getattr(entity, "id", 0)
        self.name = MessagingService.display_name_for_entity(entity)
        self.unread_count = 0
        self.archived = False
        self.is_user = getattr(entity, "is_user", False) or type(entity).__name__ == "User"
        self.is_group = (
            getattr(entity, "is_group", False)
            or type(entity).__name__ in ("Chat", "ChatForbidden")
            or bool(getattr(entity, "megagroup", False))
        )
        self.is_channel = (
            getattr(entity, "is_channel", False)
            or type(entity).__name__ == "Channel"
        )

    def __repr__(self) -> str:
        return f"PseudoDialog(id={self.id}, name={self.name!r})"


def parse_chat_targets(args: list[str]) -> list[str]:
    """
    Parse a list of chat targets supporting:
      - individual items: ['1', '2', '@alice']
      - comma-separated items: ['1,2,3', '@bob']
      - ranges: ['1-4', '6-8']
      - 'all'
    """
    targets: list[str] = []
    for arg in args:
        parts = [p.strip() for p in arg.split(",") if p.strip()]
        for part in parts:
            range_match = re.match(r"^(\d+)\s*-\s*(\d+)$", part)
            if range_match:
                start, end = int(range_match.group(1)), int(range_match.group(2))
                step = 1 if start <= end else -1
                for idx in range(start, end + step, step):
                    targets.append(str(idx))
            else:
                targets.append(part)
    return targets


class MessagingService:
    """High-level wrapper around Telethon message operations."""

    def __init__(self, client: TelegramClient) -> None:
        self._client = client
        self._dialogs: list[Any] = []
        self._folders: list[FolderInfo] = []

    # ------------------------------------------------------------------ #
    #  Dialogs & Channels
    # ------------------------------------------------------------------ #

    async def get_dialogs(
        self,
        limit: int = 50,
        folder: int | None = None,
        archived: bool | None = None,
    ) -> list[Any]:
        """Fetch dialogs and cache them for index-based access."""
        kwargs: dict[str, Any] = {"limit": limit}
        if folder is not None:
            kwargs["folder"] = folder
        if archived is not None:
            kwargs["archived"] = archived

        self._dialogs = await self._client.get_dialogs(**kwargs)
        return self._dialogs

    async def get_archived_dialogs(self, limit: int | None = 50) -> list[Any]:
        """Fetch archived dialogs and cache them."""
        return await self.get_dialogs(limit=limit, folder=1)

    async def get_channels(self, limit: int = 50) -> list[Any]:
        """Fetch dialogs and return only broadcast channels."""
        fetch_limit = limit * 3 if limit else 150
        all_dl = await self._client.get_dialogs(limit=fetch_limit)
        channels = [
            d
            for d in all_dl
            if getattr(d, "is_channel", False) and not getattr(d, "is_group", False)
        ]
        if limit:
            channels = channels[:limit]
        self._dialogs = channels
        return self._dialogs

    @property
    def dialogs(self) -> list[Any]:
        return self._dialogs

    @property
    def folders(self) -> list[FolderInfo]:
        return self._folders

    # ------------------------------------------------------------------ #
    #  Folders (Dialog Filters)
    # ------------------------------------------------------------------ #

    async def get_folders(self) -> list[FolderInfo]:
        """Fetch chat folders (dialog filters) from Telegram."""
        folders: list[FolderInfo] = [
            FolderInfo(id=0, name="All chats", is_default=True)
        ]

        try:
            res = await self._client(functions.messages.GetDialogFiltersRequest())
            raw_filters = getattr(res, "filters", res) if res else []
            for flt in raw_filters:
                if isinstance(flt, types.DialogFilterDefault):
                    continue
                name = getattr(flt, "title", None)
                if hasattr(name, "text"):
                    name = name.text
                name = str(name) if name else f"Folder {getattr(flt, 'id', '')}"
                emoticon = getattr(flt, "emoticon", None)
                folders.append(
                    FolderInfo(
                        id=getattr(flt, "id", None),
                        name=name,
                        filter_obj=flt,
                        emoticon=emoticon,
                    )
                )
        except Exception:
            pass

        folders.append(FolderInfo(id=1, name="Archived", is_archived=True))
        self._folders = folders
        return self._folders

    def find_folder(self, target: str) -> FolderInfo:
        """Find a folder by 1-based index or name."""
        if not self._folders:
            raise ValueError("Folders not loaded. Run 'chats' first.")

        target_str = str(target).strip()
        if target_str.isdigit():
            idx = int(target_str)
            if 1 <= idx <= len(self._folders):
                return self._folders[idx - 1]
            raise ValueError(
                f"Invalid folder index {idx}. Must be 1–{len(self._folders)}."
            )

        t_lower = target_str.lower()
        for f in self._folders:
            if f.name.strip().lower() == t_lower:
                return f

        for f in self._folders:
            if t_lower in f.name.strip().lower():
                return f

        raise ValueError(f"Folder '{target}' not found.")

    def find_folder_by_name(self, name: str) -> FolderInfo | None:
        """Try to find a folder by name; return None if not found."""
        if not self._folders:
            return None
        n_lower = name.strip().lower()
        for f in self._folders:
            if f.name.strip().lower() == n_lower:
                return f
        for f in self._folders:
            if n_lower in f.name.strip().lower():
                return f
        return None

    def _extract_peer_ids(self, peer: Any) -> set[int]:
        """Safely extract peer IDs (both marked and bare ID variants)."""
        ids: set[int] = set()
        if peer is None:
            return ids
        if isinstance(peer, (int, str)):
            s = str(peer).strip()
            if s.lstrip("-").isdigit():
                val = int(s)
                ids.add(val)
                try:
                    bare_id, _ = utils.resolve_id(val)
                    ids.add(bare_id)
                except Exception:
                    pass
            return ids

        if isinstance(peer, types.InputPeerSelf):
            me_id = getattr(self._client, "_self_id", None)
            if me_id:
                ids.add(me_id)
            return ids

        try:
            pid = utils.get_peer_id(peer)
            ids.add(pid)
            try:
                bare_id, _ = utils.resolve_id(pid)
                ids.add(bare_id)
            except Exception:
                pass
        except Exception:
            for attr in ("user_id", "channel_id", "chat_id"):
                val = getattr(peer, attr, None)
                if val is not None:
                    ids.add(val)
                    try:
                        bare_id, _ = utils.resolve_id(val)
                        ids.add(bare_id)
                    except Exception:
                        pass
        return ids

    async def get_folder_dialogs(
        self, folder: FolderInfo, limit: int | None = 100
    ) -> list[Any]:
        """Fetch dialogs that belong to a folder."""
        if folder.is_default:
            return await self.get_dialogs(limit=limit, folder=0)
        if folder.is_archived:
            return await self.get_archived_dialogs(limit=limit)

        df = folder.filter_obj
        if df is None or isinstance(df, types.DialogFilterDefault):
            return await self.get_dialogs(limit=limit, folder=0)

        all_dialogs = await self._client.get_dialogs(
            limit=limit * 2 if limit else None
        )

        pinned_peers = getattr(df, "pinned_peers", []) or []
        include_peers = getattr(df, "include_peers", []) or []
        exclude_peers = getattr(df, "exclude_peers", []) or []

        pinned_ids: set[int] = set()
        for p in pinned_peers:
            pinned_ids.update(self._extract_peer_ids(p))

        include_ids: set[int] = set()
        for p in include_peers:
            include_ids.update(self._extract_peer_ids(p))

        exclude_ids: set[int] = set()
        for p in exclude_peers:
            exclude_ids.update(self._extract_peer_ids(p))

        dialogs_by_id: dict[int, Any] = {}
        for d in all_dialogs:
            d_ids = self._extract_peer_ids(getattr(d, "id", None))
            ent = getattr(d, "entity", None)
            if ent:
                d_ids.update(self._extract_peer_ids(getattr(ent, "id", None)))
                d_ids.update(self._extract_peer_ids(ent))
            for i in d_ids:
                if i not in dialogs_by_id:
                    dialogs_by_id[i] = d

        result: list[Any] = []
        added_dialog_ids: set[int] = set()

        # Add pinned dialogs first in order
        for p in pinned_peers:
            p_ids = self._extract_peer_ids(p)
            if p_ids & exclude_ids:
                continue
            matched_d = None
            for i in p_ids:
                if i in dialogs_by_id:
                    matched_d = dialogs_by_id[i]
                    break
            if matched_d is not None:
                d_key = getattr(matched_d, "id", id(matched_d))
                if d_key not in added_dialog_ids:
                    result.append(matched_d)
                    added_dialog_ids.add(d_key)
            else:
                try:
                    entity = await self._client.get_entity(p)
                    d = PseudoDialog(entity)
                    d_key = getattr(d, "id", id(d))
                    if d_key not in added_dialog_ids:
                        result.append(d)
                        added_dialog_ids.add(d_key)
                except Exception:
                    pass

        # Then included dialogs
        for p in include_peers:
            p_ids = self._extract_peer_ids(p)
            if p_ids & exclude_ids:
                continue
            matched_d = None
            for i in p_ids:
                if i in dialogs_by_id:
                    matched_d = dialogs_by_id[i]
                    break
            if matched_d is not None:
                d_key = getattr(matched_d, "id", id(matched_d))
                if d_key not in added_dialog_ids:
                    result.append(matched_d)
                    added_dialog_ids.add(d_key)
            else:
                try:
                    entity = await self._client.get_entity(p)
                    d = PseudoDialog(entity)
                    d_key = getattr(d, "id", id(d))
                    if d_key not in added_dialog_ids:
                        result.append(d)
                        added_dialog_ids.add(d_key)
                except Exception:
                    pass

        # Then other matching dialogs from category rules
        for d in all_dialogs:
            d_key = getattr(d, "id", id(d))
            if d_key in added_dialog_ids:
                continue

            d_ids = self._extract_peer_ids(getattr(d, "id", None))
            ent = getattr(d, "entity", None)
            if ent:
                d_ids.update(self._extract_peer_ids(getattr(ent, "id", None)))
                d_ids.update(self._extract_peer_ids(ent))

            if d_ids & exclude_ids:
                continue

            matched = False
            if d_ids & include_ids:
                matched = True
            else:
                if getattr(df, "exclude_archived", False) and getattr(
                    d, "archived", False
                ):
                    continue
                if (
                    getattr(df, "exclude_read", False)
                    and getattr(d, "unread_count", 0) == 0
                ):
                    continue

                if (
                    getattr(df, "contacts", False)
                    and getattr(d, "is_user", False)
                    and getattr(d.entity, "contact", False)
                ):
                    matched = True
                elif (
                    getattr(df, "non_contacts", False)
                    and getattr(d, "is_user", False)
                    and not getattr(d.entity, "contact", False)
                    and not getattr(d.entity, "bot", False)
                ):
                    matched = True
                elif getattr(df, "groups", False) and getattr(d, "is_group", False):
                    matched = True
                elif (
                    getattr(df, "broadcasts", False)
                    and getattr(d, "is_channel", False)
                    and not getattr(d, "is_group", False)
                ):
                    matched = True
                elif (
                    getattr(df, "bots", False)
                    and getattr(d, "is_user", False)
                    and getattr(d.entity, "bot", False)
                ):
                    matched = True

            if matched:
                result.append(d)
                added_dialog_ids.add(d_key)

        if limit is not None:
            result = result[:limit]

        self._dialogs = result
        return self._dialogs

    # ------------------------------------------------------------------ #
    #  Archive & Folder Peer Management
    # ------------------------------------------------------------------ #

    async def resolve_target(
        self, target: str, dialogs: list[Any] | None = None
    ) -> tuple[Any, str]:
        """
        Resolve a target (index or username / id) to (entity, display_name).
        """
        dl = dialogs if dialogs is not None else self._dialogs
        target_clean = target.strip()
        target_lower = target_clean.lower()

        if target_lower in (
            "saved",
            "saved messages",
            "saved_messages",
            "saved-messages",
            "me",
        ):
            try:
                entity = await self._client.get_entity("me")
            except Exception:
                entity = await self._client.get_me()
            return entity, "Saved Messages"

        if target_clean.isdigit():
            idx = int(target_clean)
            if not dl:
                raise ValueError("No dialogs loaded. Run 'chats' or 'all chats' first.")
            if not 1 <= idx <= len(dl):
                raise ValueError(f"Invalid index {idx}. Must be 1–{len(dl)}.")
            d = dl[idx - 1]
            entity = getattr(d, "entity", d)
            name = getattr(d, "name", None) or self.display_name_for_entity(entity)
            return entity, name

        try:
            entity = await self._client.get_entity(target_clean)
        except Exception as exc:
            raise ValueError(f"Cannot resolve '{target_clean}': {exc}") from exc

        name = self.display_name_for_entity(entity)
        return entity, name

    async def archive_chats(self, targets: list[str]) -> list[str]:
        """Mass archive chats specified by index, username, or 'all'."""
        if not targets:
            raise ValueError("No targets specified.")

        dl = self._dialogs
        resolved_entities: list[Any] = []
        names: list[str] = []

        if len(targets) == 1 and targets[0].lower() == "all":
            if not dl:
                raise ValueError("No dialogs loaded to archive.")
            for d in dl:
                ent = getattr(d, "entity", d)
                resolved_entities.append(ent)
                names.append(
                    getattr(d, "name", None) or self.display_name_for_entity(ent)
                )
        else:
            for t in targets:
                ent, name = await self.resolve_target(t)
                resolved_entities.append(ent)
                names.append(name)

        await self._client.edit_folder(resolved_entities, folder=1)
        return names

    async def unarchive_chats(self, targets: list[str]) -> list[str]:
        """Mass unarchive chats specified by index, username, or 'all'."""
        if not targets:
            raise ValueError("No targets specified.")

        if len(targets) == 1 and targets[0].lower() == "all":
            await self._client.edit_folder(unpack=1)
            return ["all archived chats"]

        resolved_entities: list[Any] = []
        names: list[str] = []
        for t in targets:
            ent, name = await self.resolve_target(t)
            resolved_entities.append(ent)
            names.append(name)

        await self._client.edit_folder(resolved_entities, folder=0)
        return names

    async def add_to_folder(
        self, folder_target: str, chat_targets: list[str]
    ) -> tuple[str, list[str]]:
        """Mass add chats to a Telegram chat folder."""
        if not chat_targets:
            raise ValueError("No chats specified to add.")

        if not self._folders:
            await self.get_folders()

        folder = self.find_folder(folder_target)
        if folder.is_archived:
            names = await self.archive_chats(chat_targets)
            return folder.name, names
        if folder.is_default or not folder.filter_obj:
            raise ValueError(
                f"Cannot add chats to default folder '{folder.name}'. Choose a custom folder."
            )

        df = folder.filter_obj
        if isinstance(df, types.DialogFilterDefault):
            raise ValueError(
                f"Cannot add chats to default folder '{folder.name}'."
            )

        resolved_entities = []
        resolved_names = []
        for ct in chat_targets:
            ent, name = await self.resolve_target(ct)
            resolved_entities.append(ent)
            resolved_names.append(name)

        include_peers = list(getattr(df, "include_peers", []) or [])
        exclude_peers = list(getattr(df, "exclude_peers", []) or [])
        pinned_peers = list(getattr(df, "pinned_peers", []) or [])

        pinned_ids = {utils.get_peer_id(p) for p in pinned_peers}
        include_ids = {utils.get_peer_id(p) for p in include_peers}

        for ent in resolved_entities:
            input_peer = await self._client.get_input_entity(ent)
            peer_id = utils.get_peer_id(input_peer)
            exclude_peers = [
                p for p in exclude_peers if utils.get_peer_id(p) != peer_id
            ]
            if peer_id not in pinned_ids and peer_id not in include_ids:
                include_peers.append(input_peer)
                include_ids.add(peer_id)

        df.include_peers = include_peers
        if hasattr(df, "exclude_peers"):
            df.exclude_peers = exclude_peers

        await self._client(
            functions.messages.UpdateDialogFilterRequest(id=df.id, filter=df)
        )
        return folder.name, resolved_names

    async def remove_from_folder(
        self, folder_target: str, chat_targets: list[str]
    ) -> tuple[str, list[str]]:
        """Mass remove chats from a Telegram chat folder."""
        if not chat_targets:
            raise ValueError("No chats specified to remove.")

        if not self._folders:
            await self.get_folders()

        folder = self.find_folder(folder_target)
        if folder.is_archived:
            names = await self.unarchive_chats(chat_targets)
            return folder.name, names
        if folder.is_default or not folder.filter_obj:
            raise ValueError(
                f"Cannot remove chats from default folder '{folder.name}'. Choose a custom folder."
            )

        df = folder.filter_obj
        if isinstance(df, types.DialogFilterDefault):
            raise ValueError(
                f"Cannot remove chats from default folder '{folder.name}'."
            )

        resolved_entities = []
        resolved_names = []
        for ct in chat_targets:
            ent, name = await self.resolve_target(ct)
            resolved_entities.append(ent)
            resolved_names.append(name)

        include_peers = list(getattr(df, "include_peers", []) or [])
        exclude_peers = list(getattr(df, "exclude_peers", []) or [])
        pinned_peers = list(getattr(df, "pinned_peers", []) or [])

        for ent in resolved_entities:
            input_peer = await self._client.get_input_entity(ent)
            peer_id = utils.get_peer_id(input_peer)

            include_peers = [
                p for p in include_peers if utils.get_peer_id(p) != peer_id
            ]
            pinned_peers = [
                p for p in pinned_peers if utils.get_peer_id(p) != peer_id
            ]

            has_category_rules = any([
                getattr(df, "contacts", False),
                getattr(df, "non_contacts", False),
                getattr(df, "groups", False),
                getattr(df, "broadcasts", False),
                getattr(df, "bots", False),
            ])
            if hasattr(df, "exclude_peers") and has_category_rules:
                exclude_ids = {utils.get_peer_id(p) for p in exclude_peers}
                if peer_id not in exclude_ids:
                    exclude_peers.append(input_peer)

        df.include_peers = include_peers
        df.pinned_peers = pinned_peers
        if hasattr(df, "exclude_peers"):
            df.exclude_peers = exclude_peers

        await self._client(
            functions.messages.UpdateDialogFilterRequest(id=df.id, filter=df)
        )
        return folder.name, resolved_names

    # ------------------------------------------------------------------ #
    #  Opening
    # ------------------------------------------------------------------ #

    async def open_chat(
        self, target: str, dialogs: list[Any] | None = None
    ) -> tuple[Any, str]:
        """
        Open a chat by index (1-based), username / entity string, or 'saved'.

        Returns (entity, display_name).
        Raises ValueError on invalid index or unresolvable target.
        """
        dl = dialogs if dialogs is not None else self._dialogs
        target_clean = target.strip()
        target_lower = target_clean.lower()

        if target_lower in (
            "saved",
            "saved messages",
            "saved_messages",
            "saved-messages",
            "me",
        ):
            try:
                entity = await self._client.get_entity("me")
            except Exception:
                entity = await self._client.get_me()
            return entity, "Saved Messages"

        if target_clean.isdigit():
            idx = int(target_clean)
            if not dl:
                raise ValueError("No dialogs loaded. Run 'chats' first.")
            if not 1 <= idx <= len(dl):
                raise ValueError(
                    f"Invalid index {idx}. Must be 1–{len(dl)}."
                )
            entity = dl[idx - 1].entity
        else:
            try:
                entity = await self._client.get_entity(target_clean)
            except Exception as exc:
                raise ValueError(f"Cannot resolve '{target_clean}': {exc}") from exc

        name = self.display_name_for_entity(entity)
        return entity, name

    # ------------------------------------------------------------------ #
    #  History & Message Conversion
    # ------------------------------------------------------------------ #

    async def message_to_dict(self, msg: Any) -> dict | None:
        """Convert a Telethon message to a standardized dict."""
        if msg is None or isinstance(msg, MessageEmpty):
            return None

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
                sender_name = (
                    full or getattr(sender, "username", None) or "Unknown"
                )
        elif getattr(msg, "post", False):
            sender_name = "Channel"

        reply_to_id = None
        if getattr(msg, "reply_to", None):
            reply_to_id = getattr(msg.reply_to, "reply_to_msg_id", None)

        media = getattr(msg, "media", None)
        media_type = self._detect_media_type(media) if media else None

        return {
            "id": msg.id,
            "sender_name": sender_name,
            "text": msg.message or "",
            "date": msg.date,
            "reply_to_msg_id": reply_to_id,
            "has_media": media is not None,
            "media_type": media_type,
        }

    async def get_history(self, entity: Any, limit: int = 20) -> list[dict]:
        """
        Fetch the *limit* most recent messages in *entity*.

        Returns a list of dicts (oldest first) with keys:
            id, sender_name, text, date, reply_to_msg_id, has_media, media_type
        """
        messages = await self._client.get_messages(entity, limit=limit)
        result: list[dict] = []
        for msg in reversed(messages):
            msg_dict = await self.message_to_dict(msg)
            if msg_dict is not None:
                result.append(msg_dict)
        return result

    async def search_messages(
        self,
        query: str,
        entity: Any = None,
        limit: int = 15,
    ) -> list[dict]:
        """
        Search messages matching *query*.

        If *entity* is None, searches globally across all conversations.
        Returns a list of dicts with keys:
            id, sender_name, text, date, reply_to_msg_id, has_media, media_type,
            chat_id, chat_title, chat_username
        """
        results: list[dict] = []
        try:
            async for msg in self._client.iter_messages(entity, search=query, limit=limit):
                msg_dict = await self.message_to_dict(msg)
                if msg_dict is None:
                    continue
                chat_title = ""
                chat_username = None
                try:
                    chat = await msg.get_chat()
                    if chat:
                        chat_title = self.display_name_for_entity(chat)
                        chat_username = getattr(chat, "username", None)
                except Exception:
                    pass
                msg_dict["chat_id"] = getattr(msg, "chat_id", None)
                msg_dict["chat_title"] = chat_title
                msg_dict["chat_username"] = chat_username
                results.append(msg_dict)
        except Exception:
            pass
        return results

    async def search_dialogs(
        self,
        query: str,
        limit: int = 15,
    ) -> list[dict]:
        """
        Search dialogs/conversations by title, username, or name matching *query*.
        """
        query_lower = query.lower().strip()
        if not self._dialogs:
            await self.get_dialogs(limit=100)

        matches: list[dict] = []
        for d in self._dialogs:
            name = (d.name or "").lower()
            username = getattr(d.entity, "username", "") or ""
            username_lower = username.lower()
            first = getattr(d.entity, "first_name", "") or ""
            last = getattr(d.entity, "last_name", "") or ""
            full_name = f"{first} {last}".strip().lower()

            if (
                query_lower in name
                or query_lower in username_lower
                or query_lower in full_name
                or query_lower == str(d.id)
            ):
                matches.append({
                    "id": d.id,
                    "title": d.name,
                    "username": username,
                    "is_user": getattr(d, "is_user", False),
                    "is_group": getattr(d, "is_group", False),
                    "is_channel": getattr(d, "is_channel", False),
                })
                if len(matches) >= limit:
                    break
        return matches

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
        if getattr(entity, "is_self", False) is True:
            return "Saved Messages"
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
