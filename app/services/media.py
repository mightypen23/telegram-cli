"""
Media service – uploads, attachment discovery, downloads, and file metadata.

All Telethon media-related API calls are concentrated here.
"""

from __future__ import annotations

import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from telethon import TelegramClient, utils
from telethon.tl.types import (
    MessageEmpty,
    MessageMediaContact,
    MessageMediaDocument,
    MessageMediaGeo,
    MessageMediaGeoLive,
    MessageMediaPhoto,
)


class MediaService:
    """High-level wrapper around Telethon media operations."""

    def __init__(self, client: TelegramClient, download_dir: Path) -> None:
        self._client = client
        self._download_dir = download_dir.resolve()
        self._download_dir.mkdir(parents=True, exist_ok=True)

    @property
    def download_dir(self) -> Path:
        return self._download_dir

    # ------------------------------------------------------------------ #
    #  Uploads
    # ------------------------------------------------------------------ #

    async def upload_file(
        self,
        entity: Any,
        file_path: str,
        caption: str | None = None,
        reply_to: int | None = None,
        progress_callback: Callable | None = None,
    ) -> int:
        """
        Upload a local file to *entity*.

        Returns the sent message ID.
        Raises FileNotFoundError, PermissionError, or ValueError.
        """
        path = Path(file_path).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        if not path.is_file():
            raise ValueError(f"Not a regular file: {path}")
        if not _is_readable(path):
            raise PermissionError(f"Cannot read file: {path}")

        if reply_to is not None:
            msgs = await self._client.get_messages(entity, ids=reply_to)
            msg = msgs[0] if isinstance(msgs, list) else msgs
            if msg is None or isinstance(msg, MessageEmpty):
                raise ValueError(f"Message #{reply_to} not found in this chat.")

        cb = progress_callback or self.make_progress_callback("Uploading")

        sent = await self._client.send_file(
            entity,
            str(path),
            caption=caption or "",
            reply_to=reply_to,
            progress_callback=cb,
        )
        return sent.id

    # ------------------------------------------------------------------ #
    #  Attachment listing
    # ------------------------------------------------------------------ #

    async def get_attachments(
        self, entity: Any, limit: int = 30
    ) -> list[dict]:
        """
        Return metadata for recent messages that contain media.

        Scans the last *limit* messages (which may include text-only ones)
        and returns dicts only for those carrying media.
        """
        messages = await self._client.get_messages(entity, limit=limit)
        attachments: list[dict] = []

        for msg in reversed(messages):
            if isinstance(msg, MessageEmpty) or not getattr(msg, "media", None):
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

            media_type = self.detect_media_type(msg.media)
            filename = self._extract_filename(msg.media)
            size = self._extract_size(msg.media)

            attachments.append(
                {
                    "msg_id": msg.id,
                    "sender_name": sender_name,
                    "date": msg.date,
                    "media_type": media_type,
                    "filename": filename,
                    "size": size,
                    "caption": msg.message or None,
                }
            )

        return attachments

    # ------------------------------------------------------------------ #
    #  Downloads
    # ------------------------------------------------------------------ #

    async def download_attachment(
        self,
        entity: Any,
        msg_id: int,
        progress_callback: Callable | None = None,
    ) -> Path:
        """
        Download the media from message *msg_id* into the download directory.

        Returns the Path to the saved file.
        Raises ValueError if the message doesn't exist or has no media.
        """
        msgs = await self._client.get_messages(entity, ids=msg_id)
        msg = msgs[0] if isinstance(msgs, list) else msgs
        if msg is None or isinstance(msg, MessageEmpty):
            raise ValueError(f"Message #{msg_id} not found in this chat.")
        if not getattr(msg, "media", None):
            raise ValueError(f"Message #{msg_id} has no media attached.")

        # Determine safe destination filename in advance to avoid path traversal
        filename = self._extract_filename(msg.media)
        if not filename:
            ext = ""
            if isinstance(msg.media, MessageMediaPhoto):
                ext = ".jpg"
            elif isinstance(msg.media, MessageMediaDocument) and getattr(msg.media, "document", None):
                ext = utils.get_extension(msg.media.document) or ""
            filename = f"media_{msg_id}{ext}"

        safe_path = self.get_safe_filename(filename, self._download_dir)
        cb = progress_callback or self.make_progress_callback("Downloading")

        result = await self._client.download_media(
            msg, file=str(safe_path), progress_callback=cb
        )
        if result is None:
            raise ValueError("Download returned no file. The media may be unavailable.")

        downloaded = Path(result).resolve()

        # Security check: ensure the file is strictly inside download_dir
        if not _is_safe_path(downloaded, self._download_dir):
            safe = self.get_safe_filename(downloaded.name, self._download_dir)
            downloaded.rename(safe)
            downloaded = safe

        return downloaded

    async def open_file(self, entity: Any, msg_id: int) -> Path:
        """
        Download (if necessary) and open the attachment with xdg-open.

        Returns the path to the opened file.
        Never uses shell=True and never automatically executes downloaded files.
        """
        path = await self.download_attachment(entity, msg_id)
        if not path.exists():
            raise FileNotFoundError(f"Downloaded file not found: {path}")

        try:
            subprocess.Popen(
                ["xdg-open", str(path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            raise RuntimeError(
                "xdg-open not found. Install xdg-utils to open files."
            ) from None
        return path

    # ------------------------------------------------------------------ #
    #  Formatting
    # ------------------------------------------------------------------ #

    @staticmethod
    def format_attachment(att: dict) -> str:
        """
        Format an attachment dict for terminal display.

        Example:
            [456] Alice (14:32) [photo] sunset.jpg (2.1 MB) Beautiful view
        """
        mid = att["msg_id"]
        name = att["sender_name"]
        dt: datetime | None = att.get("date")
        time_str = dt.strftime("%H:%M") if dt else "??:??"
        mtype = att.get("media_type", "media")
        fname = att.get("filename") or "(no filename)"
        size = _format_size(att.get("size"))
        caption = att.get("caption") or ""

        line = f"[{mid}] {name} ({time_str}) [{mtype}] {fname}"
        if size:
            line += f" ({size})"
        if caption:
            line += f"  {caption}"
        return line

    # ------------------------------------------------------------------ #
    #  Media type detection
    # ------------------------------------------------------------------ #

    @staticmethod
    def detect_media_type(media: Any) -> str:
        """Return a human-readable media type string."""
        if isinstance(media, MessageMediaPhoto):
            return "photo"
        if isinstance(media, MessageMediaDocument):
            doc = media.document
            if doc:
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
                mime = getattr(doc, "mime_type", "") or ""
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

    # ------------------------------------------------------------------ #
    #  Filename safety
    # ------------------------------------------------------------------ #

    @staticmethod
    def get_safe_filename(original: str | None, download_dir: Path) -> Path:
        """
        Return a safe absolute path inside *download_dir*.

        - Strips directory components and dangerous characters.
        - Prevents path traversal.
        - Generates a name when *original* is None or empty.
        - Handles duplicates by appending _1, _2, etc.
        """
        if not original or not original.strip():
            original = f"download_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        # Strip any directory components
        name = Path(original).name
        # Remove path traversal attempts
        name = name.replace("..", "").replace("/", "").replace("\\", "")
        # Replace other problematic characters
        name = re.sub(r'[<>:"|?*\x00-\x1f]', "_", name)
        name = name.strip(". ")
        if not name:
            name = f"download_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        candidate = download_dir / name
        if not candidate.exists():
            return candidate

        stem = candidate.stem
        suffix = candidate.suffix
        counter = 1
        while True:
            candidate = download_dir / f"{stem}_{counter}{suffix}"
            if not candidate.exists():
                return candidate
            counter += 1

    # ------------------------------------------------------------------ #
    #  Progress callback
    # ------------------------------------------------------------------ #

    @staticmethod
    def make_progress_callback(action: str = "Downloading") -> Callable:
        """
        Return a Telethon-compatible progress callback.

        Prints progress like: ``Downloading: 45% (4.5 MB / 10.0 MB)``
        """

        def _callback(current: int, total: int) -> None:
            if total:
                pct = current * 100 / total
                cur_str = _format_size(current)
                tot_str = _format_size(total)
                print(
                    f"\r{action}: {pct:.0f}% ({cur_str} / {tot_str})",
                    end="",
                    flush=True,
                )
                if current >= total:
                    print()  # newline when done
            else:
                print(
                    f"\r{action}: {_format_size(current)}",
                    end="",
                    flush=True,
                )

        return _callback

    # ------------------------------------------------------------------ #
    #  Private helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _extract_filename(media: Any) -> str | None:
        """Try to extract the original filename from media."""
        if isinstance(media, MessageMediaDocument):
            doc = media.document
            if doc:
                for attr in getattr(doc, "attributes", []):
                    if type(attr).__name__ == "DocumentAttributeFilename":
                        return attr.file_name
        return None

    @staticmethod
    def _extract_size(media: Any) -> int | None:
        """Try to extract file size in bytes from media."""
        if isinstance(media, MessageMediaDocument):
            doc = media.document
            if doc:
                return getattr(doc, "size", None)
        if isinstance(media, MessageMediaPhoto):
            photo = media.photo
            if photo and hasattr(photo, "sizes") and photo.sizes:
                last = photo.sizes[-1]
                return getattr(last, "size", None)
        return None


# ====================================================================== #
#  Module-level helpers
# ====================================================================== #


def _format_size(size: int | None) -> str:
    """Format bytes into a human-readable string."""
    if size is None:
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if abs(size) < 1024:
            return f"{size:.1f} {unit}" if unit != "B" else f"{size} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _is_readable(path: Path) -> bool:
    """Check if a path is readable."""
    try:
        with path.open("rb") as f:
            f.read(1)
        return True
    except (PermissionError, OSError):
        return False


def _is_safe_path(path: Path, base: Path) -> bool:
    """Ensure *path* is within *base* directory."""
    try:
        path.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False
