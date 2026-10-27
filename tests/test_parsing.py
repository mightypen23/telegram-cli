"""Tests for command parsing – shlex, quoted paths, and edge cases."""

import shlex

import pytest


class TestCommandParsing:
    """Test that shlex handles our command formats correctly."""

    def test_simple_command(self):
        parts = shlex.split("send Hello world")
        assert parts == ["send", "Hello", "world"]

    def test_quoted_path_with_spaces(self):
        parts = shlex.split('attach "/home/user/My Documents/file.pdf"')
        assert parts == ["attach", "/home/user/My Documents/file.pdf"]

    def test_single_quoted_path(self):
        parts = shlex.split("attach '/home/user/My Documents/file.pdf'")
        assert parts == ["attach", "/home/user/My Documents/file.pdf"]

    def test_attach_with_caption(self):
        parts = shlex.split(
            'attach "/path/to/photo.jpg" --caption "Hello World"'
        )
        assert parts == [
            "attach",
            "/path/to/photo.jpg",
            "--caption",
            "Hello World",
        ]

    def test_attach_with_reply(self):
        parts = shlex.split('attach "/path/file.txt" --reply 123')
        assert parts == ["attach", "/path/file.txt", "--reply", "123"]

    def test_attach_full_options(self):
        parts = shlex.split(
            'attach "/path/to/file.pdf" --caption "My doc" --reply 456'
        )
        assert parts == [
            "attach",
            "/path/to/file.pdf",
            "--caption",
            "My doc",
            "--reply",
            "456",
        ]

    def test_reply_command(self):
        parts = shlex.split("reply 123 Thanks for sharing this!")
        assert parts[0] == "reply"
        assert parts[1] == "123"
        assert " ".join(parts[2:]) == "Thanks for sharing this!"

    def test_settings_set(self):
        parts = shlex.split("settings set history_limit 40")
        assert parts == ["settings", "set", "history_limit", "40"]

    def test_settings_set_path(self):
        parts = shlex.split("settings set download_dir ~/Downloads/telegram")
        assert parts == [
            "settings",
            "set",
            "download_dir",
            "~/Downloads/telegram",
        ]

    def test_empty_string(self):
        parts = shlex.split("")
        assert parts == []

    def test_mismatched_quotes(self):
        with pytest.raises(ValueError):
            shlex.split('attach "/unclosed/path')

    def test_escaped_quotes(self):
        parts = shlex.split(r'send He said \"hello\"')
        assert len(parts) >= 2

    def test_multiple_spaces(self):
        parts = shlex.split("send   Hello   world")
        assert parts == ["send", "Hello", "world"]

    def test_tab_characters(self):
        parts = shlex.split("send\tHello\tworld")
        assert parts == ["send", "Hello", "world"]
