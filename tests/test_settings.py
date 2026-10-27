"""Tests for app.services.settings – local settings management."""

import pytest

from app.config import Config
from app.services.settings import SettingsService


@pytest.fixture
def config(tmp_path):
    """Provide a fresh Config for each test using tmp_path."""
    cfg_file = tmp_path / "config.json"
    return Config.load(cfg_file)


@pytest.fixture
def service(config):
    return SettingsService(config)


class TestListSettings:
    def test_returns_all_settings(self, service):
        result = service.list_settings()
        assert "download_dir" in result
        assert "history_limit" in result
        assert "confirm_before_send" in result
        assert "theme" in result

    def test_returns_defaults(self, service):
        result = service.list_settings()
        assert result["history_limit"] == 20
        assert result["confirm_before_send"] is False


class TestSetSetting:
    def test_set_valid(self, service):
        msg = service.set_setting("history_limit", "50")
        assert "50" in msg
        assert service.get_setting("history_limit") == 50

    def test_set_invalid_key(self, service):
        with pytest.raises(ValueError, match="Unknown setting"):
            service.set_setting("nonexistent", "value")

    def test_set_invalid_value(self, service):
        with pytest.raises(ValueError):
            service.set_setting("history_limit", "abc")


class TestResetSetting:
    def test_reset(self, service):
        service.set_setting("history_limit", "50")
        msg = service.reset_setting("history_limit")
        assert service.get_setting("history_limit") == 20
        assert "reset" in msg.lower() or "20" in msg

    def test_reset_invalid_key(self, service):
        with pytest.raises(ValueError, match="Unknown setting"):
            service.reset_setting("nonexistent")


class TestGetValidKeys:
    def test_returns_list(self, service):
        keys = service.get_valid_keys()
        assert isinstance(keys, list)
        assert len(keys) == 4
        assert all(isinstance(k, str) for k in keys)


class TestSettingsPersistence:
    def test_set_persists(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        cfg = Config.load(cfg_file)
        svc = SettingsService(cfg)
        svc.set_setting("theme", "minimal")

        # Load fresh config from the same file
        loaded = Config.load(cfg_file)
        assert loaded.theme == "minimal"
