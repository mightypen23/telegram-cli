"""Tests for app.credentials – secure credential storage, loading, and permissions."""

import os
import stat
from unittest.mock import patch

import pytest

from app.credentials import (
    clear_credentials,
    load_credentials,
    save_credentials,
)


class TestCredentialsStorage:
    """Test saving and loading credentials with secure permissions."""

    def test_save_creates_0600_file(self, tmp_path):
        cred_file = tmp_path / ".credentials"
        saved_path = save_credentials(123456, "abcdef1234567890", cred_file)
        assert saved_path == cred_file
        assert cred_file.exists()

        # Check POSIX permissions (0600: read/write by user only)
        mode = stat.S_IMODE(os.stat(cred_file).st_mode)
        assert mode == 0o600

    def test_save_and_load(self, tmp_path):
        cred_file = tmp_path / ".credentials"
        save_credentials(987654, "my_secret_hash_value", cred_file)

        creds = load_credentials(cred_file)
        assert creds is not None
        api_id, api_hash = creds
        assert api_id == 987654
        assert api_hash == "my_secret_hash_value"

    def test_load_nonexistent_file(self, tmp_path):
        cred_file = tmp_path / "nonexistent"
        with patch.dict(os.environ, {}, clear=True):
            creds = load_credentials(cred_file)
            assert creds is None

    def test_load_corrupt_file(self, tmp_path):
        cred_file = tmp_path / ".credentials"
        cred_file.write_text("corrupted non-json content", encoding="utf-8")
        with patch.dict(os.environ, {}, clear=True):
            creds = load_credentials(cred_file)
            assert creds is None

    def test_load_missing_fields(self, tmp_path):
        cred_file = tmp_path / ".credentials"
        cred_file.write_text('{"api_id": 123}', encoding="utf-8")
        with patch.dict(os.environ, {}, clear=True):
            creds = load_credentials(cred_file)
            assert creds is None

    def test_load_from_environment(self, tmp_path):
        cred_file = tmp_path / "nonexistent"
        env = {
            "TELEGRAM_API_ID": "112233",
            "TELEGRAM_API_HASH": "env_secret_hash",
        }
        with patch.dict(os.environ, env, clear=True):
            creds = load_credentials(cred_file)
            assert creds == (112233, "env_secret_hash")

    def test_clear_credentials(self, tmp_path):
        cred_file = tmp_path / ".credentials"
        save_credentials(123, "hash", cred_file)
        assert cred_file.exists()

        assert clear_credentials(cred_file) is True
        assert not cred_file.exists()

        # Second clear returns False
        assert clear_credentials(cred_file) is False
