"""
Settings service – bridge between Config and the CLI, plus Telegram account settings.
"""

from __future__ import annotations

import time
from typing import Any

from telethon import TelegramClient
from telethon.tl.functions.account import (
    GetNotifySettingsRequest,
    GetPrivacyRequest,
    SetPrivacyRequest,
    UpdateNotifySettingsRequest,
)
from telethon.tl.types import (
    InputNotifyBroadcasts,
    InputNotifyChats,
    InputNotifyUsers,
    InputPeerNotifySettings,
    InputPrivacyKeyChatInvite,
    InputPrivacyKeyForwards,
    InputPrivacyKeyPhoneCall,
    InputPrivacyKeyPhoneNumber,
    InputPrivacyKeyPhoneP2P,
    InputPrivacyKeyProfilePhoto,
    InputPrivacyKeyStatusTimestamp,
    InputPrivacyValueAllowAll,
    InputPrivacyValueAllowContacts,
    InputPrivacyValueDisallowAll,
)

from app.config import Config


# Maps user-facing names to Telethon input privacy key classes
_PRIVACY_KEYS: dict[str, type] = {
    "phone_number": InputPrivacyKeyPhoneNumber,
    "last_seen": InputPrivacyKeyStatusTimestamp,
    "profile_photo": InputPrivacyKeyProfilePhoto,
    "forwards": InputPrivacyKeyForwards,
    "group_invite": InputPrivacyKeyChatInvite,
    "phone_call": InputPrivacyKeyPhoneCall,
    "phone_p2p": InputPrivacyKeyPhoneP2P,
}

# Maps user-facing values to Telethon input privacy value constructors
_PRIVACY_VALUES: dict[str, type] = {
    "everyone": InputPrivacyValueAllowAll,
    "contacts": InputPrivacyValueAllowContacts,
    "nobody": InputPrivacyValueDisallowAll,
}

# Maps notification peer categories to input types
_NOTIFY_PEERS: dict[str, type] = {
    "users": InputNotifyUsers,
    "chats": InputNotifyChats,
    "channels": InputNotifyBroadcasts,
}


class SettingsService:
    """Manages local CLI settings and Telegram account settings."""

    def __init__(self, config: Config) -> None:
        self._config = config

    # ------------------------------------------------------------------ #
    #  Local CLI settings
    # ------------------------------------------------------------------ #

    def list_settings(self) -> dict[str, Any]:
        """Return all current settings as a dict."""
        return self._config.to_dict()

    def set_setting(self, key: str, value: str) -> str:
        """Set a local setting. Returns a confirmation message."""
        old = self._config.get(key)
        self._config.set(key, value)
        new = self._config.get(key)
        return f"'{key}' changed: {old!r} → {new!r}"

    def reset_setting(self, key: str) -> str:
        """Reset a local setting to its default. Returns a confirmation message."""
        self._config.reset(key)
        new = self._config.get(key)
        return f"'{key}' reset to default: {new!r}"

    def get_setting(self, key: str) -> Any:
        """Get a single setting value."""
        return self._config.get(key)

    def get_valid_keys(self) -> list[str]:
        """Return the list of valid local setting keys."""
        return self._config.valid_keys()

    # ------------------------------------------------------------------ #
    #  Telegram account info (read-only)
    # ------------------------------------------------------------------ #

    async def get_account_info(self, client: TelegramClient) -> dict[str, str]:
        """
        Read basic account information.

        Returns a dict with name, username, phone (masked), and bio.
        Never exposes full credentials.
        """
        me = await client.get_me()
        about = ""
        try:
            from telethon.tl.functions.users import GetFullUserRequest

            full = await client(GetFullUserRequest(me))
            if hasattr(full, "full_user"):
                about = getattr(full.full_user, "about", "") or ""
        except Exception:
            pass

        phone = getattr(me, "phone", None) or ""
        if len(phone) > 4:
            phone = "***" + phone[-4:]

        first = me.first_name or ""
        last = me.last_name or ""
        name = f"{first} {last}".strip()

        return {
            "name": name or "(none)",
            "username": f"@{me.username}" if me.username else "(none)",
            "phone": phone or "(none)",
            "bio": about or "(none)",
        }

    # ------------------------------------------------------------------ #
    #  Telegram privacy settings
    # ------------------------------------------------------------------ #

    async def get_privacy_settings(
        self, client: TelegramClient
    ) -> dict[str, str]:
        """
        Read current privacy settings for supported keys.

        Returns a dict mapping setting name to a human-readable value.
        """
        result: dict[str, str] = {}
        for name, key_cls in _PRIVACY_KEYS.items():
            try:
                resp = await client(GetPrivacyRequest(key_cls()))
                result[name] = _interpret_privacy_rules(resp.rules)
            except Exception:
                result[name] = "(unavailable)"
        return result

    async def update_privacy(
        self,
        client: TelegramClient,
        setting: str,
        value: str,
    ) -> str:
        """
        Update a Telegram privacy setting.

        *setting*: one of the keys in _PRIVACY_KEYS
        *value*: "everyone", "contacts", or "nobody"

        Returns a result message.
        """
        if setting not in _PRIVACY_KEYS:
            valid = ", ".join(_PRIVACY_KEYS)
            raise ValueError(
                f"Unknown privacy setting '{setting}'. Valid: {valid}"
            )
        if value not in _PRIVACY_VALUES:
            valid = ", ".join(_PRIVACY_VALUES)
            raise ValueError(
                f"Invalid value '{value}'. Valid: {valid}"
            )

        key_cls = _PRIVACY_KEYS[setting]
        val_cls = _PRIVACY_VALUES[value]

        try:
            await client(
                SetPrivacyRequest(key=key_cls(), rules=[val_cls()])
            )
            return f"Privacy '{setting}' updated to '{value}'."
        except Exception as exc:
            return f"Failed to update '{setting}': {exc}"

    # ------------------------------------------------------------------ #
    #  Telegram notification settings
    # ------------------------------------------------------------------ #

    async def get_notify_settings(
        self, client: TelegramClient
    ) -> dict[str, str]:
        """
        Read notification settings for users, group chats, and channels.
        """
        result: dict[str, str] = {}
        for category, peer_cls in _NOTIFY_PEERS.items():
            try:
                resp = await client(GetNotifySettingsRequest(peer=peer_cls()))
                mute_until = getattr(resp, "mute_until", 0) or 0
                now = int(time.time())
                if mute_until > now:
                    if mute_until >= 2147483647:
                        status = "muted indefinitely"
                    else:
                        remaining_hrs = (mute_until - now) // 3600
                        status = f"muted for ~{remaining_hrs}h"
                else:
                    status = "enabled"
                result[category] = status
            except Exception:
                result[category] = "(unavailable)"
        return result

    async def update_notify_settings(
        self,
        client: TelegramClient,
        category: str,
        mute_hours: int | None,
    ) -> str:
        """
        Update notification settings.

        *category*: 'users', 'chats', or 'channels'
        *mute_hours*: None to unmute, 0 for indefinite mute, or number of hours to mute.
        """
        if category not in _NOTIFY_PEERS:
            valid = ", ".join(_NOTIFY_PEERS)
            raise ValueError(
                f"Unknown category '{category}'. Valid: {valid}"
            )

        peer_cls = _NOTIFY_PEERS[category]
        if mute_hours is None:
            mute_until = 0
            desc = "unmuted"
        elif mute_hours == 0:
            mute_until = 2147483647  # max 32-bit int: forever
            desc = "muted indefinitely"
        else:
            mute_until = int(time.time()) + (mute_hours * 3600)
            desc = f"muted for {mute_hours}h"

        try:
            settings = InputPeerNotifySettings(mute_until=mute_until)
            await client(
                UpdateNotifySettingsRequest(peer=peer_cls(), settings=settings)
            )
            return f"Notifications for {category} {desc}."
        except Exception as exc:
            return f"Failed to update notifications for {category}: {exc}"


def _interpret_privacy_rules(rules: list) -> str:
    """Convert Telethon privacy rules list to a human-readable string."""
    names = [type(r).__name__ for r in rules]
    for n in names:
        if "AllowAll" in n:
            return "everyone"
        if "AllowContacts" in n:
            return "contacts"
        if "DisallowAll" in n:
            return "nobody"
    return ", ".join(names) if names else "(unknown)"
