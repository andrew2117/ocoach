"""Gemini 3 and 4 reject a tool-call replay that has no thought signature.

`langchain-google-genai` 4.4 keeps the signature the model returned
(`additional_kwargs["__gemini_function_call_thought_signatures__"]`) and, when
history has none, sends the API's skip sentinel instead of an unsigned
function call. The agent history repair must not drop that map.
"""

from __future__ import annotations

import unittest

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_google_genai.chat_models import (
    _FUNCTION_CALL_THOUGHT_SIGNATURES_MAP_KEY,
    _parse_chat_history,
)

from agent.graph import _safeguard_tool_history

_SIGNATURES = _FUNCTION_CALL_THOUGHT_SIGNATURES_MAP_KEY


def _tool_turn(signatures: dict[str, str] | None = None) -> list:
    message = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "get_user_stats",
                "args": {"handle": "tourist"},
                "id": "call-1",
                "type": "tool_call",
            }
        ],
        additional_kwargs={_SIGNATURES: signatures} if signatures else {},
    )
    return [
        HumanMessage(content="How is tourist doing?"),
        message,
        ToolMessage(content="rating 4000", tool_call_id="call-1"),
    ]


class GeminiThoughtSignatureTests(unittest.TestCase):
    def test_history_repair_keeps_function_call_signatures(self) -> None:
        history = _tool_turn({"call-1": "c2lnbmF0dXJl"})
        repaired = _safeguard_tool_history(history)
        assistant = next(message for message in repaired if isinstance(message, AIMessage))
        self.assertEqual(assistant.additional_kwargs[_SIGNATURES]["call-1"], "c2lnbmF0dXJl")

    def test_missing_signature_is_filled_for_gemini_4(self) -> None:
        _, formatted = _parse_chat_history(_tool_turn(), model="gemini-4-argon")
        model_turn = next(message for message in formatted if message.role == "model")
        function_call = next(part for part in model_turn.parts if part.function_call)
        self.assertTrue(function_call.thought_signature)

    def test_stored_signature_is_replayed(self) -> None:
        _, formatted = _parse_chat_history(
            _tool_turn({"call-1": "c2lnbmF0dXJl"}),
            model="gemini-3.8-flash",
        )
        model_turn = next(message for message in formatted if message.role == "model")
        function_call = next(part for part in model_turn.parts if part.function_call)
        self.assertEqual(function_call.thought_signature, b"signature")
