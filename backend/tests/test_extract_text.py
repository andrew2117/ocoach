"""Streamed reply text must stay markdown for every provider.

The chat UI renders one string. OpenAI, Anthropic, and Gemini put that
string in different chunk shapes; tool and reasoning blocks must not leak
into it.
"""

from __future__ import annotations

import unittest

from services.agent import _extract_text

_FORMULA = r"runs in $O(N \log N)$ and \(O(N)\)"


class ExtractTextTests(unittest.TestCase):
    def test_openai_chat_string_is_kept(self) -> None:
        self.assertEqual(_extract_text(_FORMULA), _FORMULA)

    def test_openai_responses_output_text_is_kept(self) -> None:
        content = [
            {"type": "reasoning", "summary": [{"type": "summary_text", "text": "hidden"}]},
            {"type": "output_text", "text": _FORMULA},
        ]
        self.assertEqual(_extract_text(content), _FORMULA)

    def test_anthropic_text_blocks_skip_thinking_and_tool_use(self) -> None:
        content = [
            {"type": "thinking", "thinking": "plan the hull"},
            {"type": "text", "text": "Andrew's scan ", "index": 0},
            {"type": "text", "text": _FORMULA, "index": 1},
            {"type": "tool_use", "id": "t1", "name": "get_user_stats", "input": {}},
        ]
        self.assertEqual(_extract_text(content), f"Andrew's scan {_FORMULA}")

    def test_gemini_text_blocks_skip_function_call_signatures(self) -> None:
        content = [
            {"type": "text", "text": _FORMULA},
            {"type": "function_call_signature", "signature": "abc"},
        ]
        self.assertEqual(_extract_text(content), _FORMULA)
