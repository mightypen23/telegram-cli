"""
Persistent local configuration for Telegram CLI.

Stores settings in ~/.config/telegram-cli/config.json with validation,
safe defaults, and atomic writes.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


CONFIG_DIR = Path.home() / ".config" / "telegram-cli"
CONFIG_FILE = CONFIG_DIR / "config.json"

VALID_THEMES = ("default", "minimal", "colorful")

# Project root is one level up from app/
PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Config:
    """Persistent local CLI configuration."""

    download_dir: str = "downloads"
    history_limit: int = 20
    confirm_before_send: bool = False
    theme: str = "default"

    # Internal path to config file for persistence (not serialized)
    _config_file: Path | None = field(
        default=None,
        init=False,
        repr=False,
        compare=False,
    )

    # ---- class-level metadata (not stored) ----
    _DEFAULTS: dict[str, Any] = field(
        default_factory=lambda: {
            "download_dir": "downloads",
            "history_limit": 20,
            "confirm_before_send": False,
            "theme": "default",
        },
        init=False,
        repr=False,
        compare=False,
    )

    _VALIDATORS: dict[str, str] = field(
        default_factory=lambda: {
            "download_dir": "Valid directory path",
            "history_limit": "Integer between 1 and 100",
            "confirm_before_send": "true or false",
            "theme": f"One of: {', '.join(VALID_THEMES)}",
        },
        init=False,
        repr=False,
        compare=False,
    )

    # ------------------------------------------------------------------ #
    #  Persistence
    # ------------------------------------------------------------------ #

    @classmethod
    def load(cls, config_file: Path | None = None) -> Config:
        """Load configuration from disk, or return defaults."""
        target_file = config_file or CONFIG_FILE
        if target_file.exists():
            try:
                data = json.loads(target_file.read_text(encoding="utf-8"))
                # Only accept known keys
                known = {k for k in cls.__dataclass_fields__ if not k.startswith("_")}
                filtered = {k: v for k, v in data.items() if k in known}
                cfg = cls(**filtered)
                # Re-validate loaded values; fall back to defaults on error
                cfg._clamp_values()
                cfg._config_file = target_file
                return cfg
            except (json.JSONDecodeError, TypeError, ValueError):
                pass
        cfg = cls()
        cfg._config_file = target_file
        return cfg

    def save(self, config_file: Path | None = None) -> None:
        """Atomically write configuration to disk."""
        target_file = config_file or self._config_file or CONFIG_FILE
        target_dir = target_file.parent
        target_dir.mkdir(parents=True, exist_ok=True)
        data = self.to_dict()
        # Write to a temp file in the same directory, then atomically rename
        fd, tmp_path = tempfile.mkstemp(
            dir=str(target_dir), suffix=".tmp", prefix="config_"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
                fh.write("\n")
            os.replace(tmp_path, str(target_file))
            self._config_file = target_file
        except BaseException:
            # Clean up temp file on failure
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    # ------------------------------------------------------------------ #
    #  Getters / setters
    # ------------------------------------------------------------------ #

    def get(self, key: str) -> Any:
        """Return the value of a setting by name."""
        self._require_key(key)
        return getattr(self, key)

    def set(self, key: str, value: str) -> None:
        """
        Set a configuration value from a string.

        Validates and coerces the type automatically.
        Raises ValueError for invalid keys or values.
        """
        self._require_key(key)
        coerced = self._coerce(key, value)
        setattr(self, key, coerced)
        self.save()

    def reset(self, key: str) -> None:
        """Reset a single setting to its default value."""
        self._require_key(key)
        default = self._DEFAULTS[key]
        setattr(self, key, default)
        self.save()

    def to_dict(self) -> dict[str, Any]:
        """Return a plain dict of all settings (excluding internals)."""
        return {
            k: v
            for k, v in asdict(self).items()
            if not k.startswith("_")
        }

    def get_download_path(self) -> Path:
        """
        Return the resolved absolute download directory.

        Creates the directory if it doesn't exist.
        """
        p = Path(self.download_dir).expanduser()
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        p = p.resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p

    @staticmethod
    def valid_keys() -> list[str]:
        """Return the list of user-facing setting keys."""
        return ["download_dir", "history_limit", "confirm_before_send", "theme"]

    # ------------------------------------------------------------------ #
    #  Internal helpers
    # ------------------------------------------------------------------ #

    def _require_key(self, key: str) -> None:
        if key not in self.valid_keys():
            valid = ", ".join(self.valid_keys())
            raise ValueError(f"Unknown setting '{key}'. Valid keys: {valid}")

    def _coerce(self, key: str, raw: str) -> Any:
        """Validate and coerce a raw string value for *key*."""
        if key == "history_limit":
            try:
                val = int(raw)
            except ValueError:
                raise ValueError("history_limit must be an integer.") from None
            if not 1 <= val <= 100:
                raise ValueError("history_limit must be between 1 and 100.")
            return val

        if key == "confirm_before_send":
            low = raw.strip().lower()
            if low in ("true", "1", "yes", "on"):
                return True
            if low in ("false", "0", "no", "off"):
                return False
            raise ValueError("confirm_before_send must be true or false.")

        if key == "theme":
            low = raw.strip().lower()
            if low not in VALID_THEMES:
                raise ValueError(
                    f"theme must be one of: {', '.join(VALID_THEMES)}"
                )
            return low

        if key == "download_dir":
            stripped = raw.strip()
            if not stripped:
                raise ValueError("download_dir cannot be empty.")
            return str(Path(stripped).expanduser())

        return raw  # pragma: no cover

    def _clamp_values(self) -> None:
        """Silently fix out-of-range values loaded from disk."""
        if not isinstance(self.history_limit, int) or not 1 <= self.history_limit <= 100:
            self.history_limit = self._DEFAULTS["history_limit"]
        if self.theme not in VALID_THEMES:
            self.theme = self._DEFAULTS["theme"]
        if not isinstance(self.confirm_before_send, bool):
            self.confirm_before_send = self._DEFAULTS["confirm_before_send"]
