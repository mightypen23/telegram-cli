"""
Telegram CLI – application entry point and lifecycle.

Handles authentication, client setup, and the main event loop.
Preserves the existing Telegram session.
"""

import asyncio
import sys
from getpass import getpass

from telethon import TelegramClient

from app.cli import CLI
from app.config import Config
from app.credentials import load_credentials, save_credentials


SESSION = "telegram_session"


async def get_or_prompt_credentials() -> tuple[int, str]:
    """
    Retrieve Telegram credentials from secure storage or prompt interactively.

    Never prints or logs the API hash.
    """
    creds = load_credentials()
    if creds is not None:
        print("Using saved Telegram API credentials.")
        return creds

    print("No saved Telegram credentials found.")
    api_id_text = input("Telegram API ID: ").strip()
    api_hash = getpass("Telegram API hash: ").strip()

    try:
        api_id = int(api_id_text)
    except ValueError:
        print("API ID must be a number.")
        sys.exit(1)

    if not api_hash:
        print("API hash cannot be empty.")
        sys.exit(1)

    try:
        save_choice = (
            input("Save credentials securely in ~/.config/telegram-cli/.credentials? [Y/n]: ")
            .strip()
            .lower()
        )
    except (EOFError, KeyboardInterrupt):
        save_choice = "n"

    if save_choice in ("", "y", "yes"):
        save_credentials(api_id, api_hash)
        print("Credentials saved securely (permissions 0600 - user read/write only).\n")

    return api_id, api_hash


async def main() -> None:
    """Entry point: authenticate and launch the interactive CLI."""
    api_id, api_hash = await get_or_prompt_credentials()

    config = Config.load()
    client = TelegramClient(SESSION, api_id, api_hash)

    try:
        await client.start()
        print("\nConnected to Telegram.")

        cli = CLI(client, config)
        await cli.run()

    finally:
        await client.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExiting.")
        sys.exit(0)
