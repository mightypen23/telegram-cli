"""Tests for app.services.ai – AI reasoning, tool dispatch, and draft management."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.ai import AIAssistantService, Draft


@pytest.fixture
def mock_messaging():
    svc = MagicMock()
    svc.open_chat = AsyncMock(return_value=(MagicMock(), "Bob"))
    svc.search_messages = AsyncMock(return_value=[
        {
            "id": 101,
            "sender_name": "Bob",
            "text": "Let's meet tomorrow at 10am",
            "date": "2026-11-04 10:00:00",
            "chat_title": "Bob",
            "chat_username": "bob123",
        }
    ])
    svc.search_dialogs = AsyncMock(return_value=[
        {"id": 12345, "title": "Bob", "username": "bob123", "is_user": True}
    ])
    svc.get_history = AsyncMock(return_value=[
        {"sender_name": "Bob", "text": "Hello!", "date": "2026-11-04 09:00:00"}
    ])
    svc.send_message = AsyncMock(return_value=555)
    return svc


class TestDraftManagement:
    @pytest.mark.asyncio
    async def test_create_and_confirm_draft(self, mock_messaging):
        ai = AIAssistantService(mock_messaging)
        res, draft = await ai._dispatch_tool("draft_message", {"recipient": "Bob", "message": "On my way"})
        assert draft is not None
        assert draft.recipient == "Bob"
        assert draft.message == "On my way"
        assert draft.status == "pending"

        latest = ai.get_latest_draft()
        assert latest is draft

        ok, msg = await ai.confirm_draft(draft.id)
        assert ok is True
        assert "555" in msg
        assert draft.status == "sent"
        mock_messaging.send_message.assert_awaited_once()

    def test_cancel_draft(self, mock_messaging):
        ai = AIAssistantService(mock_messaging)
        draft = Draft(id="d1", recipient="Alice", message="Hi")
        ai._pending_drafts["d1"] = draft

        ok, msg = ai.cancel_draft("d1")
        assert ok is True
        assert draft.status == "cancelled"

    @pytest.mark.asyncio
    async def test_confirm_nonexistent_draft(self, mock_messaging):
        ai = AIAssistantService(mock_messaging)
        ok, msg = await ai.confirm_draft("missing_id")
        assert ok is False


class TestToolDispatch:
    @pytest.mark.asyncio
    async def test_search_messages_dispatch(self, mock_messaging):
        ai = AIAssistantService(mock_messaging)
        res, draft = await ai._dispatch_tool("search_messages", {"query": "meet tomorrow"})
        assert draft is None
        assert res["count"] == 1
        assert res["results"][0]["sender"] == "Bob"

    @pytest.mark.asyncio
    async def test_search_chats_dispatch(self, mock_messaging):
        ai = AIAssistantService(mock_messaging)
        res, draft = await ai._dispatch_tool("search_chats", {"query": "Bob"})
        assert draft is None
        assert len(res["matches"]) == 1

    @pytest.mark.asyncio
    async def test_get_chat_history_dispatch(self, mock_messaging):
        ai = AIAssistantService(mock_messaging)
        res, draft = await ai._dispatch_tool("get_chat_history", {"chat_target": "Bob", "limit": 5})
        assert draft is None
        assert res["chat"] == "Bob"
        assert len(res["messages"]) == 1


class TestOllamaQueryFlow:
    @pytest.mark.asyncio
    async def test_ask_direct_text_response(self, mock_messaging):
        ai = AIAssistantService(mock_messaging)

        fake_resp = {
            "message": {
                "role": "assistant",
                "content": "Hello! How can I help you?",
            }
        }

        with patch.object(ai, "_call_ollama_sync", return_value=fake_resp):
            resp = await ai.ask("Hi")
            assert resp.text == "Hello! How can I help you?"
            assert resp.draft is None
            assert len(resp.tools_called) == 0

    @pytest.mark.asyncio
    async def test_ask_with_tool_calling(self, mock_messaging):
        ai = AIAssistantService(mock_messaging)

        # Step 1: LLM calls search_messages tool
        step1_resp = {
            "message": {
                "role": "assistant",
                "tool_calls": [
                    {
                        "function": {
                            "name": "search_messages",
                            "arguments": {"query": "dinner tonight"},
                        }
                    }
                ],
            }
        }

        # Step 2: LLM produces final answer
        step2_resp = {
            "message": {
                "role": "assistant",
                "content": "Bob suggested Italian at 7pm.",
            }
        }

        with patch.object(ai, "_call_ollama_sync", side_effect=[step1_resp, step2_resp]):
            resp = await ai.ask("Where are we having dinner?")
            assert resp.text == "Bob suggested Italian at 7pm."
            assert "search_messages" in resp.tools_called

    @pytest.mark.asyncio
    async def test_session_history_memory(self, mock_messaging):
        ai = AIAssistantService(mock_messaging)

        resp1 = {"message": {"role": "assistant", "content": "The meeting is at 2pm."}}
        resp2 = {"message": {"role": "assistant", "content": "Yes, in room 4B."}}

        with patch.object(ai, "_call_ollama_sync", side_effect=[resp1, resp2]):
            # Turn 1
            await ai.ask("When is the meeting?", session_id="user_123")
            history = ai.get_session_history("user_123")
            assert len(history) == 2
            assert history[0]["content"] == "When is the meeting?"
            assert history[1]["content"] == "The meeting is at 2pm."

            # Turn 2
            await ai.ask("Is it in the main office?", session_id="user_123")
            history2 = ai.get_session_history("user_123")
            assert len(history2) == 4
            assert history2[2]["content"] == "Is it in the main office?"
            assert history2[3]["content"] == "Yes, in room 4B."

            # Clear history
            ai.clear_session_history("user_123")
            assert len(ai.get_session_history("user_123")) == 0
