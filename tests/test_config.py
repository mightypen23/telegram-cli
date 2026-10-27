"""Tests for app.config – Config loading, saving, validation, and defaults."""

import json
from pathlib import Path

import pytest

from app.config import Config


class TestConfigDefaults:
    """Test default configuration values."""

    def test_default_download_dir(self):
        cfg = Config()
        assert cfg.download_dir == "downloads"

    def test_default_history_limit(self):
        cfg = Config()
        assert cfg.history_limit == 20

    def test_default_confirm_before_send(self):
        cfg = Config()
        assert cfg.confirm_before_send is False

    def test_default_theme(self):
        cfg = Config()
        assert cfg.theme == "default"

    def test_valid_keys(self):
        keys = Config.valid_keys()
        assert "download_dir" in keys
        assert "history_limit" in keys
        assert "confirm_before_send" in keys
        assert "theme" in keys
        assert len(keys) == 4

    def test_to_dict(self):
        cfg = Config()
        d = cfg.to_dict()
        assert isinstance(d, dict)
        assert d["download_dir"] == "downloads"
        assert d["history_limit"] == 20
        assert d["confirm_before_send"] is False
        assert d["theme"] == "default"
        for k in d:
            assert not k.startswith("_")


class TestConfigValidation:
    """Test setting validation and coercion."""

    def test_set_valid_history_limit(self, tmp_path):
        cfg = Config.load(tmp_path / "config.json")
        cfg.set("history_limit", "50")
        assert cfg.history_limit == 50

    def test_set_history_limit_min(self, tmp_path):
        cfg = Config.load(tmp_path / "config.json")
        cfg.set("history_limit", "1")
        assert cfg.history_limit == 1

    def test_set_history_limit_max(self, tmp_path):
        cfg = Config.load(tmp_path / "config.json")
        cfg.set("history_limit", "100")
        assert cfg.history_limit == 100

    def test_set_history_limit_too_low(self, tmp_path):
        cfg = Config.load(tmp_path / "config.json")
        with pytest.raises(ValueError, match="between 1 and 100"):
            cfg.set("history_limit", "0")

    def test_set_history_limit_too_high(self, tmp_path):
        cfg = Config.load(tmp_path / "config.json")
        with pytest.raises(ValueError, match="between 1 and 100"):
            cfg.set("history_limit", "101")

    def test_set_history_limit_not_int(self, tmp_path):
        cfg = Config.load(tmp_path / "config.json")
        with pytest.raises(ValueError, match="integer"):
            cfg.set("history_limit", "abc")

    def test_set_confirm_true(self, tmp_path):
        cfg = Config.load(tmp_path / "config.json")
        for val in ("true", "True", "TRUE", "1", "yes", "on"):
            cfg.set("confirm_before_send", val)
            assert cfg.confirm_before_send is True

    def test_set_confirm_false(self, tmp_path):
        cfg = Config.load(tmp_path / "config.json")
        for val in ("false", "False", "FALSE", "0", "no", "off"):
            cfg.set("confirm_before_send", val)
            assert cfg.confirm_before_send is False

    def test_set_confirm_invalid(self, tmp_path):
        cfg = Config.load(tmp_path / "config.json")
        with pytest.raises(ValueError, match="true or false"):
            cfg.set("confirm_before_send", "maybe")

    def test_set_valid_theme(self, tmp_path):
        cfg = Config.load(tmp_path / "config.json")
        for t in ("default", "minimal", "colorful"):
            cfg.set("theme", t)
            assert cfg.theme == t

    def test_set_invalid_theme(self, tmp_path):
        cfg = Config.load(tmp_path / "config.json")
        with pytest.raises(ValueError, match="theme must be one of"):
            cfg.set("theme", "dark")

    def test_set_download_dir(self, tmp_path):
        cfg = Config.load(tmp_path / "config.json")
        cfg.set("download_dir", "/tmp/my_downloads")
        assert cfg.download_dir == "/tmp/my_downloads"

    def test_set_download_dir_tilde(self, tmp_path):
        cfg = Config.load(tmp_path / "config.json")
        cfg.set("download_dir", "~/telegram_downloads")
        assert "~" not in cfg.download_dir
        assert "telegram_downloads" in cfg.download_dir

    def test_set_download_dir_empty(self, tmp_path):
        cfg = Config.load(tmp_path / "config.json")
        with pytest.raises(ValueError, match="cannot be empty"):
            cfg.set("download_dir", "")

    def test_set_unknown_key(self, tmp_path):
        cfg = Config.load(tmp_path / "config.json")
        with pytest.raises(ValueError, match="Unknown setting"):
            cfg.set("nonexistent_key", "value")

    def test_get_unknown_key(self):
        cfg = Config()
        with pytest.raises(ValueError, match="Unknown setting"):
            cfg.get("nonexistent_key")


class TestConfigPersistence:
    """Test save and load operations."""

    def test_save_and_load(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        cfg = Config.load(cfg_file)
        cfg.set("history_limit", "42")
        cfg.set("theme", "minimal")
        cfg.save()

        loaded = Config.load(cfg_file)
        assert loaded.history_limit == 42
        assert loaded.theme == "minimal"
        assert loaded.download_dir == "downloads"
        assert loaded.confirm_before_send is False

    def test_load_missing_file(self, tmp_path):
        cfg_file = tmp_path / "missing.json"
        cfg = Config.load(cfg_file)
        assert cfg.history_limit == 20
        assert cfg.theme == "default"

    def test_load_corrupt_json(self, tmp_path):
        cfg_file = tmp_path / "corrupt.json"
        cfg_file.write_text("not valid json {{{", encoding="utf-8")
        cfg = Config.load(cfg_file)
        assert cfg.history_limit == 20

    def test_load_ignores_unknown_keys(self, tmp_path):
        cfg_file = tmp_path / "unknown.json"
        data = {"history_limit": 30, "unknown_key": "value"}
        cfg_file.write_text(json.dumps(data), encoding="utf-8")
        cfg = Config.load(cfg_file)
        assert cfg.history_limit == 30

    def test_load_clamps_invalid_values(self, tmp_path):
        cfg_file = tmp_path / "invalid.json"
        data = {"history_limit": 999, "theme": "nonexistent"}
        cfg_file.write_text(json.dumps(data), encoding="utf-8")
        cfg = Config.load(cfg_file)
        assert cfg.history_limit == 20
        assert cfg.theme == "default"

    def test_atomic_write(self, tmp_path):
        cfg_file = tmp_path / "atomic.json"
        cfg = Config.load(cfg_file)
        cfg.set("history_limit", "33")
        cfg.save()

        content = cfg_file.read_text(encoding="utf-8")
        data = json.loads(content)
        assert data["history_limit"] == 33


class TestConfigReset:
    """Test resetting individual settings."""

    def test_reset_history_limit(self, tmp_path):
        cfg = Config.load(tmp_path / "config.json")
        cfg.set("history_limit", "50")
        assert cfg.history_limit == 50
        cfg.reset("history_limit")
        assert cfg.history_limit == 20

    def test_reset_unknown_key(self, tmp_path):
        cfg = Config.load(tmp_path / "config.json")
        with pytest.raises(ValueError, match="Unknown setting"):
            cfg.reset("nonexistent")


class TestConfigDownloadPath:
    """Test get_download_path resolution."""

    def test_relative_path(self):
        cfg = Config()
        path = cfg.get_download_path()
        assert path.is_absolute()
        assert path.exists()

    def test_absolute_path(self, tmp_path):
        cfg = Config()
        test_dir = tmp_path / "my_downloads"
        cfg.download_dir = str(test_dir)
        path = cfg.get_download_path()
        assert path == test_dir.resolve()
        assert path.exists()
