"""
AI Assistant service – local LLM reasoning via Ollama with Telegram tool calling.

Supports searching messages, locating chats by context, drafting and sending messages
on behalf of the user with draft-first safety confirmation.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from app.services.messaging import MessagingService

logger = logging.getLogger(__name__)


@dataclass
class Draft:
    """Represents a pending message draft waiting for user confirmation."""

    id: str
    recipient: str
    message: str
    reply_to_msg_id: int | None = None
    created_at: float = field(default_factory=time.time)
    status: str = "pending"  # "pending", "confirmed", "cancelled", "sent"


@dataclass
class AIResponse:
    """Result of an AI query."""

    text: str
    draft: Draft | None = None
    tools_called: list[str] = field(default_factory=list)


AI_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_messages",
            "description": (
                "Search messages across all chats or within a specific chat for keywords, "
                "topics, or context. Use this to find conversations where a specific subject was discussed."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search keywords or topic (e.g. 'project deadline', 'meeting', 'dinner')",
                    },
                    "chat_target": {
                        "type": "string",
                        "description": "Optional chat username, title, or index to limit the search to a specific chat",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_chats",
            "description": "Search user's chats/dialogs by name, title, or username.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Name or username of the person or group",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_chat_history",
            "description": (
                "Retrieve recent messages from a specific chat. "
                "Useful to get context on what was recently discussed in a chat."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "chat_target": {
                        "type": "string",
                        "description": "Username, title, or index of the chat",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of recent messages to fetch (default: 15)",
                    },
                },
                "required": ["chat_target"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "draft_message",
            "description": (
                "Prepare a draft message to send to a person or chat on behalf of the user. "
                "ALWAYS call this when the user asks to send or reply to a message."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "recipient": {
                        "type": "string",
                        "description": "Username, chat title, or index of the recipient",
                    },
                    "message": {
                        "type": "string",
                        "description": "The exact message content to send",
                    },
                    "reply_to_msg_id": {
                        "type": "integer",
                        "description": "Optional message ID to reply to",
                    },
                },
                "required": ["recipient", "message"],
            },
        },
    },
]

SYSTEM_PROMPT = """\
You are an intelligent, capable personal AI assistant integrated into Telegram.
You act on behalf of the account owner. You have direct tools to:
1. Search messages across conversations for specific context or keywords.
2. Search and locate specific chats and contacts.
3. Retrieve recent conversation history in any chat.
4. Draft messages to be sent on the owner's behalf.

RULES:
- When the owner asks to find where something was discussed or find a chat with someone about a topic, use `search_messages` or `search_chats` to locate the information first.
- When the owner asks you to send, reply, or forward a message, ALWAYS call `draft_message`. All messages require user confirmation before being dispatched.
- Context Awareness: Remember previous turns in this conversation. Use prior context to resolve ambiguous references (like 'he', 'she', 'that chat', 'to him', 'yesterday', 'that meeting').
- Once a tool returns data, summarize findings clearly, accurately, and concisely. Mention the chat name/sender and timestamp if helpful.
- Maintain a helpful, polite, and executive personal assistant tone.
"""


def build_system_prompt(
    owner_info: str = "",
    chat_context: str = "",
    is_owner: bool = True,
) -> str:
    """Construct dynamic, context-aware system prompt with current time and identity."""
    now_str = datetime.now().strftime("%A, %Y-%m-%d %H:%M")
    base = (
        f"You are an AI assistant on Telegram (with a clever, sharp, witty personality like Grok on X).\n"
        f"Current local time: {now_str}.\n"
        "You are engaging, insightful, smart, helpful, and speak with personality.\n"
    )
    if is_owner:
        if owner_info:
            base += f"You are interacting with your owner ({owner_info}).\n"
        base += (
            "You have direct tools on the owner's behalf to:\n"
            "1. Search messages across conversations for specific context or keywords.\n"
            "2. Search and locate specific chats and contacts.\n"
            "3. Retrieve recent conversation history in any chat.\n"
            "4. Draft messages to be sent on the owner's behalf.\n\n"
            "RULES FOR OWNER ACTIONS:\n"
            "- Multi-Turn Context: Remember previous turns in this conversation. Use previous context to resolve references.\n"
            "- When the owner asks to find where something was discussed or find a chat with someone about a topic, use `search_messages` or `search_chats` to locate the information first.\n"
            "- When the owner asks you to send, reply, or forward a message, ALWAYS call `draft_message`. All messages require confirmation before being dispatched.\n"
        )
    else:
        base += (
            "You are chatting publicly in a group, channel, or direct message with a user.\n"
            "Answer questions, chat, explain concepts, summarize, or provide witty and helpful answers to anyone who talks to you (just like Grok on X).\n"
            "Never give robotic refusal disclaimers (like 'I only work for @user'). Just be helpful and engaging.\n"
        )

    base += (
        "\nGENERAL RULES:\n"
        "- Answer naturally, directly, and engagingly.\n"
        "- Use conversation and group context to understand context and references.\n"
    )

    if chat_context:
        base += f"\nACTIVE CHAT & CONVERSATION CONTEXT:\n{chat_context}\n"

    return base


def _clean_arg_str(val: Any) -> str:
    """Normalize string arguments that might arrive as dicts or objects from LLMs."""
    if val is None:
        return ""
    if isinstance(val, dict):
        return str(val.get("name") or val.get("username") or val.get("title") or val.get("object") or "")
    return str(val).strip()


class AIAssistantService:
    """Manages AI reasoning, tool execution, and message drafting."""

    def __init__(
        self,
        messaging_service: MessagingService,
        ollama_url: str = "http://localhost:11434",
        model: str = "qwen2.5:3b",
        draft_first: bool = True,
        max_history_turns: int = 12,
    ) -> None:
        self._messaging = messaging_service
        self.ollama_url = ollama_url.rstrip("/")
        self.model = model
        self.draft_first = draft_first
        self.max_history_turns = max_history_turns
        self._pending_drafts: dict[str, Draft] = {}
        self._session_histories: dict[str, list[dict[str, str]]] = {}

    @property
    def pending_drafts(self) -> dict[str, Draft]:
        return self._pending_drafts

    def get_latest_draft(self) -> Draft | None:
        """Return the most recently created pending draft, or None."""
        pending = [d for d in self._pending_drafts.values() if d.status == "pending"]
        if not pending:
            return None
        return max(pending, key=lambda d: d.created_at)

    def get_session_history(self, session_id: str) -> list[dict[str, str]]:
        """Return rolling conversation history for a given session."""
        return list(self._session_histories.get(session_id, []))

    def add_session_message(self, session_id: str, role: str, content: str) -> None:
        """Add a message to the session's rolling memory."""
        if not session_id or not content.strip():
            return
        if session_id not in self._session_histories:
            self._session_histories[session_id] = []
        self._session_histories[session_id].append({"role": role, "content": content.strip()})
        # Prune to max_history_turns
        if len(self._session_histories[session_id]) > self.max_history_turns:
            self._session_histories[session_id] = self._session_histories[session_id][-self.max_history_turns:]

    def clear_session_history(self, session_id: str | None = None) -> None:
        """Clear conversation memory for a session (or all sessions if None)."""
        if session_id:
            self._session_histories.pop(session_id, None)
        else:
            self._session_histories.clear()

    async def ask(
        self,
        prompt: str,
        chat_context: str | None = None,
        conversation_history: list[dict[str, str]] | None = None,
        session_id: str | None = None,
        owner_info: str | None = None,
        is_owner: bool = True,
    ) -> AIResponse:
        """
        Send a prompt to the AI model, handle function calling, and return the response.
        Automatically utilizes and updates rolling conversation history when session_id is provided.
        """
        system_content = build_system_prompt(
            owner_info=owner_info or "",
            chat_context=chat_context or "",
            is_owner=is_owner,
        )

        messages: list[dict[str, Any]] = [{"role": "system", "content": system_content}]

        # Inject session history if conversation_history is not explicitly passed
        if conversation_history is not None:
            messages.extend(conversation_history)
        elif session_id:
            messages.extend(self.get_session_history(session_id))

        messages.append({"role": "user", "content": prompt})

        tools_called: list[str] = []
        new_draft: Draft | None = None

        # Loop up to 4 iterations for multi-step tool calls
        for _ in range(4):
            payload: dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "stream": False,
            }
            if is_owner:
                payload["tools"] = AI_TOOLS

            try:
                response_data = await asyncio.to_thread(
                    self._call_ollama_sync, payload
                )
            except Exception as exc:
                logger.error("Failed to call Ollama: %s", exc)
                return AIResponse(
                    text=f"Error connecting to local Ollama service: {exc}\nEnsure Ollama is running (`ollama serve`).",
                )

            msg = response_data.get("message", {})
            tool_calls = msg.get("tool_calls") or []

            if not tool_calls:
                # No more tools needed; assistant produced text
                final_text = msg.get("content", "").strip()
                if not final_text and new_draft:
                    final_text = (
                        f"I have prepared a draft to **{new_draft.recipient}**:\n\n"
                        f"> {new_draft.message}\n\n"
                        "Please confirm if you would like me to send this message."
                    )

                result_text = final_text or "Task completed."

                # Update session history if session_id is tracked
                if session_id:
                    self.add_session_message(session_id, "user", prompt)
                    self.add_session_message(session_id, "assistant", result_text)

                return AIResponse(
                    text=result_text,
                    draft=new_draft,
                    tools_called=tools_called,
                )

            # Append the assistant message with tool calls to conversation
            messages.append(msg)

            for call in tool_calls:
                func = call.get("function", {})
                tool_name = func.get("name", "")
                raw_args = func.get("arguments", {})
                if isinstance(raw_args, str):
                    try:
                        args = json.loads(raw_args)
                    except Exception:
                        args = {}
                else:
                    args = dict(raw_args)

                tools_called.append(tool_name)
                tool_result, draft_obj = await self._dispatch_tool(tool_name, args)
                if draft_obj:
                    new_draft = draft_obj

                messages.append({
                    "role": "tool",
                    "content": json.dumps(tool_result, default=str),
                })

        return AIResponse(
            text="Completed tool execution.",
            draft=new_draft,
            tools_called=tools_called,
        )

    async def _dispatch_tool(
        self, name: str, args: dict[str, Any]
    ) -> tuple[Any, Draft | None]:
        """Execute a tool and return (result_data, draft_or_none)."""
        if name == "search_messages":
            query = _clean_arg_str(args.get("query", ""))
            target = _clean_arg_str(args.get("chat_target"))
            entity = None
            if target:
                try:
                    entity, _ = await self._messaging.open_chat(target)
                except Exception:
                    pass

            results = await self._messaging.search_messages(query, entity=entity, limit=10)
            formatted = []
            for m in results:
                formatted.append({
                    "chat": m.get("chat_title") or m.get("chat_username") or "Direct/Group",
                    "sender": m.get("sender_name"),
                    "text": m.get("text"),
                    "date": str(m.get("date")),
                    "msg_id": m.get("id"),
                })
            return {"count": len(formatted), "results": formatted}, None

        elif name == "search_chats":
            query = _clean_arg_str(args.get("query", ""))
            matches = await self._messaging.search_dialogs(query, limit=10)
            return {"matches": matches}, None

        elif name == "get_chat_history":
            target = _clean_arg_str(args.get("chat_target", ""))
            limit = int(args.get("limit") or 15)
            try:
                entity, name_str = await self._messaging.open_chat(target)
                history = await self._messaging.get_history(entity, limit=limit)
                msgs = [
                    {"sender": m.get("sender_name"), "text": m.get("text"), "date": str(m.get("date"))}
                    for m in history
                ]
                return {"chat": name_str, "messages": msgs}, None
            except Exception as exc:
                return {"error": f"Could not retrieve history for '{target}': {exc}"}, None

        elif name in ("draft_message", "send_message"):
            recipient = _clean_arg_str(args.get("recipient", ""))
            message = _clean_arg_str(args.get("message", ""))
            reply_to = args.get("reply_to_msg_id")
            if reply_to is not None:
                try:
                    reply_to = int(reply_to)
                except (ValueError, TypeError):
                    reply_to = None

            draft_id = uuid.uuid4().hex[:8]
            draft = Draft(
                id=draft_id,
                recipient=recipient,
                message=message,
                reply_to_msg_id=reply_to,
            )
            self._pending_drafts[draft_id] = draft

            return {
                "status": "draft_created",
                "draft_id": draft_id,
                "recipient": recipient,
                "message": message,
                "note": "Draft created successfully. Awaiting user confirmation before sending.",
            }, draft

        return {"error": f"Unknown tool: {name}"}, None

    async def confirm_draft(self, draft_id: str | None = None) -> tuple[bool, str]:
        """
        Send a pending draft message on behalf of the user.
        If draft_id is not specified, confirms the latest pending draft.
        """
        if draft_id and draft_id in self._pending_drafts:
            draft = self._pending_drafts[draft_id]
        else:
            draft = self.get_latest_draft()

        if not draft or draft.status != "pending":
            return False, "No pending message draft found to send."

        try:
            entity, resolved_name = await self._messaging.open_chat(draft.recipient)
            sent_id = await self._messaging.send_message(
                entity, draft.message, reply_to=draft.reply_to_msg_id
            )
            draft.status = "sent"
            return True, f"✅ Message sent to {resolved_name} (ID: #{sent_id}):\n\"{draft.message}\""
        except Exception as exc:
            return False, f"Failed to send message to '{draft.recipient}': {exc}"

    def cancel_draft(self, draft_id: str | None = None) -> tuple[bool, str]:
        """Cancel a pending draft message."""
        if draft_id and draft_id in self._pending_drafts:
            draft = self._pending_drafts[draft_id]
        else:
            draft = self.get_latest_draft()

        if not draft or draft.status != "pending":
            return False, "No pending draft found to cancel."

        draft.status = "cancelled"
        return True, f"❌ Cancelled message draft to {draft.recipient}."

    def _call_ollama_sync(self, payload: dict[str, Any], timeout: float = 60.0) -> dict[str, Any]:
        """Synchronous HTTP call to Ollama endpoint."""
        url = f"{self.ollama_url}/api/chat"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)
