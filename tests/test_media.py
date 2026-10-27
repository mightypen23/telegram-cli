"""Tests for app.services.media – filename safety, formatting, progress, and validation."""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.media import MediaService, _format_size


class TestSafeFilename:
    """Test filename sanitization and path traversal prevention."""

    @pytest.fixture
    def download_dir(self, tmp_path):
        return tmp_path / "downloads"

    def test_simple_filename(self, download_dir):
        result = MediaService.get_safe_filename("report.pdf", download_dir)
        assert result.parent == download_dir
        assert result.name == "report.pdf"

    def test_path_traversal_dots(self, download_dir):
        result = MediaService.get_safe_filename("../../etc/passwd", download_dir)
        assert result.parent == download_dir
        assert ".." not in str(result)

    def test_path_traversal_absolute(self, download_dir):
        result = MediaService.get_safe_filename("/etc/passwd", download_dir)
        assert result.parent == download_dir
        assert result.name == "passwd"

    def test_none_filename(self, download_dir):
        result = MediaService.get_safe_filename(None, download_dir)
        assert result.parent == download_dir
        assert result.name.startswith("download_")

    def test_empty_filename(self, download_dir):
        result = MediaService.get_safe_filename("", download_dir)
        assert result.parent == download_dir
        assert result.name.startswith("download_")

    def test_special_characters(self, download_dir):
        result = MediaService.get_safe_filename('file<>:"|?.txt', download_dir)
        assert result.parent == download_dir
        assert "<" not in result.name
        assert ">" not in result.name
        assert "?" not in result.name

    def test_duplicate_filename(self, download_dir):
        download_dir.mkdir(parents=True, exist_ok=True)
        (download_dir / "photo.jpg").touch()
        result = MediaService.get_safe_filename("photo.jpg", download_dir)
        assert result.name == "photo_1.jpg"

    def test_multiple_duplicates(self, download_dir):
        download_dir.mkdir(parents=True, exist_ok=True)
        (download_dir / "doc.pdf").touch()
        (download_dir / "doc_1.pdf").touch()
        result = MediaService.get_safe_filename("doc.pdf", download_dir)
        assert result.name == "doc_2.pdf"

    def test_windows_path_in_name(self, download_dir):
        result = MediaService.get_safe_filename(
            "C:\\Users\\someone\\file.txt", download_dir
        )
        assert result.parent == download_dir
        assert "\\" not in result.name


class TestFormatAttachment:
    """Test attachment formatting for terminal display."""

    def test_full_attachment(self):
        att = {
            "msg_id": 456,
            "sender_name": "Alice",
            "date": datetime(2025, 6, 15, 14, 32, tzinfo=timezone.utc),
            "media_type": "photo",
            "filename": "sunset.jpg",
            "size": 2_200_000,
            "caption": "Beautiful view",
        }
        result = MediaService.format_attachment(att)
        assert "[456]" in result
        assert "Alice" in result
        assert "[photo]" in result
        assert "sunset.jpg" in result
        assert "Beautiful view" in result

    def test_no_filename(self):
        att = {
            "msg_id": 789,
            "sender_name": "Bob",
            "date": datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc),
            "media_type": "photo",
            "filename": None,
            "size": None,
            "caption": None,
        }
        result = MediaService.format_attachment(att)
        assert "(no filename)" in result

    def test_no_caption(self):
        att = {
            "msg_id": 100,
            "sender_name": "Carol",
            "date": None,
            "media_type": "document",
            "filename": "data.csv",
            "size": 1024,
            "caption": None,
        }
        result = MediaService.format_attachment(att)
        assert "data.csv" in result
        assert "??:??" in result


class TestFormatSize:
    """Test human-readable file size formatting."""

    def test_bytes(self):
        assert _format_size(500) == "500 B"

    def test_kilobytes(self):
        result = _format_size(1536)
        assert "KB" in result

    def test_megabytes(self):
        result = _format_size(2_500_000)
        assert "MB" in result

    def test_gigabytes(self):
        result = _format_size(5_000_000_000)
        assert "GB" in result

    def test_none(self):
        assert _format_size(None) == ""

    def test_zero(self):
        assert _format_size(0) == "0 B"


class TestFileUploadValidation:
    """Test file path validation for uploads."""

    @pytest.fixture
    def service(self, tmp_path):
        client = AsyncMock()
        return MediaService(client, tmp_path / "downloads")

    async def test_nonexistent_file(self, service):
        entity = MagicMock()
        with pytest.raises(FileNotFoundError):
            await service.upload_file(entity, "/nonexistent/file.txt")

    async def test_directory_instead_of_file(self, service, tmp_path):
        entity = MagicMock()
        d = tmp_path / "a_directory"
        d.mkdir()
        with pytest.raises(ValueError, match="Not a regular file"):
            await service.upload_file(entity, str(d))

    async def test_valid_file(self, service, tmp_path):
        entity = MagicMock()
        f = tmp_path / "test.txt"
        f.write_text("hello")

        sent_msg = MagicMock()
        sent_msg.id = 77
        service._client.send_file = AsyncMock(return_value=sent_msg)

        msg_id = await service.upload_file(entity, str(f))
        assert msg_id == 77

    async def test_upload_with_invalid_reply_target(self, service, tmp_path):
        entity = MagicMock()
        f = tmp_path / "test.txt"
        f.write_text("hello")
        service._client.get_messages = AsyncMock(return_value=[None])

        with pytest.raises(ValueError, match="not found"):
            await service.upload_file(entity, str(f), reply_to=99999)


class TestProgressCallback:
    """Test progress callback formatting."""

    def test_callback_creation(self):
        cb = MediaService.make_progress_callback("Testing")
        assert callable(cb)

    def test_callback_runs(self, capsys):
        cb = MediaService.make_progress_callback("Downloading")
        cb(500, 1000)
        captured = capsys.readouterr()
        assert "50%" in captured.out
        assert "Downloading" in captured.out

    def test_callback_complete(self, capsys):
        cb = MediaService.make_progress_callback("Uploading")
        cb(1000, 1000)
        captured = capsys.readouterr()
        assert "100%" in captured.out
