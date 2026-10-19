"""Phase 9: context-window trimming and Anthropic tool-history invariants."""

from __future__ import annotations

import unittest

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.messages.utils import count_tokens_approximately

from agent.graph import (
    AGENT_CONTEXT_MAX_TOKENS,
    _EMPTY_AI_PLACEHOLDER,
    _safeguard_tool_history,
    _trim_state_messages_for_llm,
)
from agent.tools import LLM_TOOL_OUTPUT_MAX_CHARS, TRUNCATION_WARNING, _format_result


def _tool_call(call_id: str, name: str = "search_cp_knowledge") -> dict[str, object]:
    return {"id": call_id, "name": name, "args": {"query": "x"}, "type": "tool_call"}


def _tool_use_block(call_id: str, name: str = "search_cp_knowledge") -> dict[str, object]:
    return {"type": "tool_use", "id": call_id, "name": name, "input": {"query": "x"}}


def _anthropic_role(msg: object) -> str:
    return "assistant" if isinstance(msg, AIMessage) else "user"


def assert_alternating_human_ai(messages: list[object]) -> None:
    """Anthropic requires user/assistant alternation after the system prompt.

    ``ToolMessage`` is a user-role turn (tool_result). Consecutive tool results
    after one assistant tool_use turn are allowed; Human/AI must not clump.
    """
    if not messages:
        return
    assert isinstance(messages[0], HumanMessage), "history must start on HumanMessage"
    prev = messages[0]
    pending_tool_ids: set[str] = set()
    for msg in messages[1:]:
        if isinstance(prev, HumanMessage):
            assert isinstance(msg, AIMessage), f"Human must be followed by AI, got {type(msg).__name__}"
        elif isinstance(prev, AIMessage):
            if prev.tool_calls:
                assert isinstance(msg, ToolMessage), "AI tool_use must be followed by ToolMessage"
                pending_tool_ids = {
                    str(tool_call.get("id")) for tool_call in prev.tool_calls if tool_call.get("id")
                }
            else:
                assert isinstance(msg, HumanMessage), "text AI must be followed by Human"
                pending_tool_ids = set()
        elif isinstance(prev, ToolMessage):
            assert isinstance(msg, (ToolMessage, AIMessage)), "tool result must be followed by tool result or AI"
            if isinstance(msg, HumanMessage):  # pragma: no cover - guarded by isinstance above
                raise AssertionError("ToolMessage cannot be followed by HumanMessage")
        if isinstance(msg, ToolMessage):
            assert msg.tool_call_id in pending_tool_ids or (
                isinstance(prev, ToolMessage) and msg.tool_call_id in pending_tool_ids
            )
            if isinstance(prev, AIMessage):
                pending_tool_ids = {
                    str(tool_call.get("id")) for tool_call in prev.tool_calls if tool_call.get("id")
                }
        if isinstance(msg, AIMessage) and not msg.tool_calls:
            pending_tool_ids = set()
        prev = msg

    roles = [_anthropic_role(msg) for msg in messages]
    for left, right, left_msg, right_msg in zip(roles, roles[1:], messages, messages[1:]):
        if left == right == "assistant":
            raise AssertionError("consecutive assistant messages")
        if left == right == "user" and isinstance(left_msg, HumanMessage) and isinstance(right_msg, HumanMessage):
            raise AssertionError("consecutive HumanMessages")
        if left == right == "user" and isinstance(left_msg, HumanMessage) and isinstance(right_msg, ToolMessage):
            raise AssertionError("HumanMessage followed by ToolMessage")
        if left == right == "user" and isinstance(left_msg, ToolMessage) and isinstance(right_msg, HumanMessage):
            raise AssertionError("ToolMessage followed by HumanMessage")


class ToolOutputTruncationTests(unittest.TestCase):
    def test_stdout_is_hard_capped_before_state(self) -> None:
        payload = {
            "language": "c++",
            "version": "13.0.0",
            "compile": {"code": 0, "stdout": "", "stderr": ""},
            "run": {
                "code": 0,
                "stdout": "x" * 20_000,
                "stderr": "",
                "wall_time": 12,
                "memory": 2048,
            },
        }
        formatted = _format_result(payload)
        self.assertLessEqual(len(formatted), LLM_TOOL_OUTPUT_MAX_CHARS)
        self.assertIn(TRUNCATION_WARNING, formatted)
        self.assertLess(count_tokens_approximately([ToolMessage(content=formatted, tool_call_id="t1")]), AGENT_CONTEXT_MAX_TOKENS)

    def test_oversized_tool_result_does_not_wipe_trim_window(self) -> None:
        payload = {
            "language": "c++",
            "version": "13.0.0",
            "compile": {"code": 0, "stdout": "", "stderr": ""},
            "run": {
                "code": 0,
                "stdout": "y" * 50_000,
                "stderr": "e" * 50_000,
                "wall_time": 12,
                "memory": 2048,
            },
        }
        history = [
            HumanMessage(content="please run this"),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "t1",
                        "name": "compile_and_test_cpp",
                        "args": {"source_code": "int main(){}", "standard_input": ""},
                        "type": "tool_call",
                    }
                ],
            ),
            ToolMessage(content=_format_result(payload), tool_call_id="t1", name="compile_and_test_cpp"),
        ]
        trimmed = _trim_state_messages_for_llm(history)
        self.assertTrue(trimmed)
        assert_alternating_human_ai(trimmed)
        self.assertTrue(any(isinstance(msg, ToolMessage) for msg in trimmed))


class SafeguardToolHistoryTests(unittest.TestCase):
    def test_strips_orphaned_tool_use_blocks_from_content(self) -> None:
        ai = AIMessage(
            content=[
                {"type": "text", "text": "I'll run this."},
                _tool_use_block("t1", "compile_and_test_cpp"),
                _tool_use_block("t2"),
            ],
            tool_calls=[
                _tool_call("t1", "compile_and_test_cpp"),
                _tool_call("t2"),
            ],
        )
        result = _safeguard_tool_history(
            [
                HumanMessage(content="check this"),
                ai,
                ToolMessage(content="ok", tool_call_id="t1", name="compile_and_test_cpp"),
            ]
        )
        assert_alternating_human_ai(result)
        synced = result[1]
        assert isinstance(synced, AIMessage)
        self.assertEqual([tool_call.get("id") for tool_call in synced.tool_calls], ["t1"])
        assert isinstance(synced.content, list)
        tool_use_ids = [block.get("id") for block in synced.content if isinstance(block, dict) and block.get("type") == "tool_use"]
        self.assertEqual(tool_use_ids, ["t1"])
        self.assertEqual(synced.content[0], {"type": "text", "text": "I'll run this."})

    def test_placeholder_when_only_orphaned_tool_use_remains(self) -> None:
        ai = AIMessage(
            content=[_tool_use_block("t1")],
            tool_calls=[_tool_call("t1")],
        )
        result = _safeguard_tool_history([HumanMessage(content="q"), ai])
        assert_alternating_human_ai(result)
        self.assertEqual(len(result), 2)
        synced = result[1]
        assert isinstance(synced, AIMessage)
        self.assertEqual(synced.tool_calls, [])
        self.assertEqual(synced.content, _EMPTY_AI_PLACEHOLDER)

    def test_empty_text_blocks_are_treated_as_empty(self) -> None:
        ai = AIMessage(
            content=[{"type": "text", "text": "   "}, _tool_use_block("t1")],
            tool_calls=[_tool_call("t1")],
        )
        result = _safeguard_tool_history([HumanMessage(content="q"), ai, HumanMessage(content="next")])
        assert_alternating_human_ai(result)
        assistants = [msg for msg in result if isinstance(msg, AIMessage)]
        self.assertEqual(assistants[0].content, _EMPTY_AI_PLACEHOLDER)
        self.assertEqual(assistants[0].tool_calls, [])

    def test_complete_tool_pair_is_preserved(self) -> None:
        history = [
            HumanMessage(content="q"),
            AIMessage(
                content=[{"type": "text", "text": "calling"}, _tool_use_block("t1")],
                tool_calls=[_tool_call("t1")],
            ),
            ToolMessage(content="result", tool_call_id="t1", name="search_cp_knowledge"),
            AIMessage(content="done"),
        ]
        result = _safeguard_tool_history(history)
        assert_alternating_human_ai(result)
        self.assertEqual(len(result), 4)
        self.assertEqual(result[1].tool_calls[0]["id"], "t1")  # type: ignore[union-attr]

    def test_merges_consecutive_humans_after_dropped_assistant(self) -> None:
        result = _safeguard_tool_history(
            [
                HumanMessage(content="first"),
                HumanMessage(content="second"),
            ]
        )
        assert_alternating_human_ai(result)
        self.assertEqual(len(result), 1)
        assert isinstance(result[0], HumanMessage)
        self.assertIn("first", str(result[0].content))
        self.assertIn("second", str(result[0].content))

    def test_inserts_placeholder_between_tool_result_and_human(self) -> None:
        result = _safeguard_tool_history(
            [
                HumanMessage(content="q"),
                AIMessage(content="", tool_calls=[_tool_call("t1")]),
                ToolMessage(content="result", tool_call_id="t1", name="search_cp_knowledge"),
                HumanMessage(content="follow up"),
            ]
        )
        assert_alternating_human_ai(result)
        self.assertIsInstance(result[-2], AIMessage)
        self.assertEqual(result[-2].content, _EMPTY_AI_PLACEHOLDER)  # type: ignore[union-attr]


class TrimWindowTests(unittest.TestCase):
    def test_long_history_starts_on_human_and_alternates(self) -> None:
        history: list[object] = []
        for i in range(80):
            history.append(HumanMessage(content=f"question {i} about dp " * 20))
            history.append(AIMessage(content=f"hint {i} use knapsack " * 20))
        history.extend(
            [
                HumanMessage(content="please test this"),
                AIMessage(
                    content=[{"type": "text", "text": "running"}, _tool_use_block("t1", "compile_and_test_cpp")],
                    tool_calls=[_tool_call("t1", "compile_and_test_cpp")],
                ),
                ToolMessage(content="Status: Accepted\nStdout: 1", tool_call_id="t1", name="compile_and_test_cpp"),
            ]
        )
        trimmed = _trim_state_messages_for_llm(history)  # type: ignore[arg-type]
        self.assertTrue(trimmed)
        assert_alternating_human_ai(trimmed)
        self.assertLessEqual(count_tokens_approximately(trimmed), AGENT_CONTEXT_MAX_TOKENS)


if __name__ == "__main__":
    unittest.main()
