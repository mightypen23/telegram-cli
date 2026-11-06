"""Tests for CLI 'ai' and 'bot' commands in app.cli."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.cli import CLI
from app.config import Config
from app.services.ai import AIResponse, Draft


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.is_connected = MagicMock(return_value=True)
    client.add_event_handler = MagicMock()
    user = MagicMock()
    user.id = 7522968153
    user.username = "alezwel"
    client.get_me = AsyncMock(return_value=user)
    return client


class TestCLIAICommand:
    @pytest.mark.asyncio
    async def test_cmd_ai_text_response(self, mock_client, capsys):
        cfg = Config()
        cli = CLI(mock_client, cfg)
        cli._ai.ask = AsyncMock(return_value=AIResponse(text="Found meeting at 3pm"))

        await cli._cmd_ai(["when", "is", "the", "meeting"])

        captured = capsys.readouterr().out
        assert "Found meeting at 3pm" in captured
        cli._ai.ask.assert_awaited_once_with(
            "when is the meeting", chat_context=None, session_id="cli"
        )

    @pytest.mark.asyncio
    async def test_cmd_ai_clear_history(self, mock_client, capsys):
        cfg = Config()
        cli = CLI(mock_client, cfg)
        cli._ai.clear_session_history = MagicMock()

        await cli._cmd_ai(["clear"])

        captured = capsys.readouterr().out
        assert "memory cleared" in captured
        cli._ai.clear_session_history.assert_called_once_with("cli")

    @pytest.mark.asyncio
    async def test_cmd_ai_draft_confirmed(self, mock_client, capsys):
        cfg = Config()
        cli = CLI(mock_client, cfg)
        draft = Draft(id="d100", recipient="Bob", message="See you soon")
        cli._ai.ask = AsyncMock(return_value=AIResponse(text="Draft ready", draft=draft))
        cli._ai.confirm_draft = AsyncMock(return_value=(True, "Message sent to Bob!"))

        with patch.object(cli, "_async_input", return_value="y"):
            await cli._cmd_ai(["tell", "bob", "see", "you", "soon"])

        captured = capsys.readouterr().out
        assert "Message Draft:" in captured
        assert "Message sent to Bob!" in captured
        cli._ai.confirm_draft.assert_awaited_once_with("d100")

    @pytest.mark.asyncio
    async def test_cmd_ai_draft_cancelled(self, mock_client, capsys):
        cfg = Config()
        cli = CLI(mock_client, cfg)
        draft = Draft(id="d101", recipient="Bob", message="Wait")
        cli._ai.ask = AsyncMock(return_value=AIResponse(text="Draft ready", draft=draft))
        cli._ai.cancel_draft = MagicMock(return_value=(True, "Draft cancelled"))

        with patch.object(cli, "_async_input", return_value="n"):
            await cli._cmd_ai(["tell", "bob", "wait"])

        captured = capsys.readouterr().out
        assert "Draft cancelled." in captured
        cli._ai.cancel_draft.assert_called_once_with("d101")


class TestCLIBotCommand:
    @pytest.mark.asyncio
    async def test_cmd_bot_status_offline(self, mock_client, capsys):
        cfg = Config()
        cli = CLI(mock_client, cfg)

        await cli._cmd_bot(["status"])
        captured = capsys.readouterr().out
        assert "OFFLINE" in captured

    @pytest.mark.asyncio
    async def test_cmd_bot_status_online(self, mock_client, capsys):
        cfg = Config()
        mock_bot = MagicMock()
        mock_bot.is_running = True
        mock_bot.bot_username = "mightypen_bot"

        cli = CLI(mock_client, cfg, bot_service=mock_bot)

        await cli._cmd_bot(["status"])
        captured = capsys.readouterr().out
        assert "ONLINE: @mightypen_bot" in captured
