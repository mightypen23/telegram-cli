"""
Secure storage and retrieval of Telegram API credentials.

Stores credentials in ~/.config/telegram-cli/.credentials with strict
POSIX permissions (0600 - user read/write only).
Secrets are kept strictly separate from non-secret config.json.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Tuple


CREDENTIALS_DIR = Path.home() / ".config" / "telegram-cli"
CREDENTIALS_FILE = CREDENTIALS_DIR / ".credentials"
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_credentials(file_path: Path | None = None) -> Tuple[int, str] | None:
    """
    Retrieve Telegram credentials from environment or secure storage.

    Order of precedence:
    1. Environment variables: TELEGRAM_API_ID and TELEGRAM_API_HASH
       (or API_ID and API_HASH)
    2. Local .env file in the project root
    3. User credentials file (~/.config/telegram-cli/.credentials)

    Returns (api_id, api_hash) if found, otherwise None.
    Never prints or logs the credentials.
    """
    # 1. Check environment variables
    env_id = os.environ.get("TELEGRAM_API_ID") or os.environ.get("API_ID")
    env_hash = os.environ.get("TELEGRAM_API_HASH") or os.environ.get("API_HASH")
    if env_id and env_hash:
        try:
            return int(env_id.strip()), env_hash.strip()
        except ValueError:
            pass

    # 2. Check local .env in project root
    project_env = PROJECT_ROOT / ".env"
    if project_env.exists():
        creds = _parse_env_file(project_env)
        if creds:
            return creds

    # 3. Check ~/.config/telegram-cli/.credentials
    target = file_path or CREDENTIALS_FILE
    if target.exists():
        try:
            content = target.read_text(encoding="utf-8")
            data = json.loads(content)
            api_id = int(data.get("api_id", 0))
            api_hash = str(data.get("api_hash", "")).strip()
            if api_id and api_hash:
                return api_id, api_hash
        except (json.JSONDecodeError, ValueError, TypeError, OSError):
            pass

    return None


def save_credentials(
    api_id: int, api_hash: str, file_path: Path | None = None
) -> Path:
    """
    Save credentials with strict 0600 permissions (user read/write only).

    Returns the Path to the saved credentials file.
    """
    target = file_path or CREDENTIALS_FILE
    target.parent.mkdir(parents=True, exist_ok=True)

    data = json.dumps({"api_id": api_id, "api_hash": api_hash.strip()}, indent=2)

    # Use os.open to guarantee 0600 creation mode atomically
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(str(target), flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(data)
            fh.write("\n")
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        raise

    # Enforce 0600 permissions in case the file already existed
    os.chmod(target, 0o600)
    return target


def clear_credentials(file_path: Path | None = None) -> bool:
    """
    Delete stored credentials if present.

    Returns True if a file was deleted, False if none existed.
    """
    target = file_path or CREDENTIALS_FILE
    if target.exists():
        try:
            target.unlink()
            return True
        except OSError:
            pass
    return False


def _parse_env_file(path: Path) -> Tuple[int, str] | None:
    """Parse key=value pairs from a .env file safely."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None

    env_map: dict[str, str] = {}
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip().strip("'\"")
        env_map[key] = val

    api_id_val = env_map.get("TELEGRAM_API_ID") or env_map.get("API_ID")
    api_hash_val = env_map.get("TELEGRAM_API_HASH") or env_map.get("API_HASH")

    if api_id_val and api_hash_val:
        try:
            return int(api_id_val), api_hash_val
        except ValueError:
            pass
    return None
