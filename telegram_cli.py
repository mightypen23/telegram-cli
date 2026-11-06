"""
Telegram CLI – application entry point and lifecycle.

Handles authentication, client setup, and the main event loop.
Preserves the existing Telegram session.
"""

import asyncio
import sys
from getpass import getpass

from telethon import TelegramClient

from pathlib import Path

from app.cli import CLI
from app.config import Config
from app.credentials import load_bot_token, load_credentials, save_credentials
from app.services.ai import AIAssistantService
from app.services.bot import AIBotService
from app.services.messaging import MessagingService


PROJECT_ROOT = Path(__file__).resolve().parent
SESSION = str(PROJECT_ROOT / "telegram_session")
BOT_SESSION = str(PROJECT_ROOT / "bot_session")


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
    """Entry point: authenticate and launch the interactive CLI or bot daemon."""
    api_id, api_hash = await get_or_prompt_credentials()

    config = Config.load()
    client = TelegramClient(SESSION, api_id, api_hash)
    bot_service: AIBotService | None = None
    bot_client: TelegramClient | None = None

    try:
        await client.start()
        print("\nConnected to Telegram.")

        # Check for bot token and launch AI Assistant Bot
        bot_token = load_bot_token()
        if bot_token:
            bot_client = TelegramClient(BOT_SESSION, api_id, api_hash)
            messaging = MessagingService(client)
            ai_service = AIAssistantService(
                messaging,
                ollama_url=config.ollama_url,
                model=config.ai_model,
                draft_first=config.ai_draft_first,
            )
            bot_service = AIBotService(bot_client, client, ai_service)
            try:
                await bot_service.start(bot_token)
                print(
                    f"AI Assistant Bot online: @{bot_service.bot_username} "
                    f"(Model: {config.ai_model}, restricted to @{bot_service.owner_username})"
                )
            except Exception as exc:
                print(f"Notice: Could not start AI Bot: {exc}")

        # If --bot flag is passed, run in standalone daemon mode
        if "--bot" in sys.argv:
            if not bot_service or not bot_service.is_running:
                print("Error: AI Bot is not running. Please verify your bot token.")
                return
            print(
                f"\nAI Assistant Bot daemon running as @{bot_service.bot_username}.\n"
                "You can now chat with your bot from Telegram Desktop / Mobile.\n"
                "Press Ctrl+C to exit."
            )
            await client.run_until_disconnected()
            return

        cli = CLI(client, config, bot_service=bot_service)
        await cli.run()

    finally:
        if bot_service:
            try:
                await bot_service.stop()
            except Exception:
                pass
        await client.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExiting.")
        sys.exit(0)
