"""Streaming entry point into the LangGraph CP coach agent (`agent/graph.py`).

Phase 6 replaced this module's own graph construction + manually-reloaded
Supabase chat history with the process-wide checkpointed graph from
`agent/graph.py`: `AsyncPostgresSaver` now recalls prior turns for a given
`thread_id` automatically (see `backend/main.py` for how the checkpointer is
wired up), so this module only needs to hand the graph today's new human
message plus a `RunnableConfig` — it never re-sends history itself.

The `services/db.py` `chats` table is unrelated to that memory now: it's
kept purely so the frontend can render a session's message log (a simple
role/content list), while the checkpointer is the graph's actual working
memory (full message objects, including tool calls/results). See
`routes/chat.py`.

Phase 8: `stream_agent_reply` yields typed stream events (tokens plus
`compile_and_test_cpp` tool lifecycle) so the frontend can render execution
cards while the agent is running.

Phase 10: generalized tool-lifecycle streaming to the three read-only
domain tools (`search_cp_knowledge`, `get_user_stats`,
`get_upcoming_contests`) as well, so the frontend can surface loading
states and structured cards (`CodeforcesStatsCard`, `RAGCitationBadge`) for
those too, not just C++ execution. All four now use
`response_format="content_and_artifact"`, so `on_tool_end` output always
carries a structured `.artifact` dict alongside its LLM-facing text.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from typing import Any

from langchain_core.messages import AIMessageChunk, HumanMessage
from langgraph.errors import GraphRecursionError

from agent.graph import get_graph
from agent.models import MissingProviderKeyError, UnknownModelError, resolve_model
from agent.tools import build_cpp_execution_result
from core.config import settings

logger = logging.getLogger(__name__)

CPP_EXECUTION_TOOL = "compile_and_test_cpp"

# Every tool the frontend has a card/badge for — see `frontend/lib/api.ts`'s
# `ToolName` union, which must stay in sync with this set.
STREAMED_TOOL_NAMES = {
    CPP_EXECUTION_TOOL,
    "search_cp_knowledge",
    "get_user_stats",
    "get_upcoming_contests",
}


def _extract_text(content: Any) -> str:
    """Anthropic streams content as either a plain string or a list of
    blocks (text / tool_use / thinking); only plain text should reach the
    client — tool-call argument deltas aren't user-facing text. OpenAI and
    Gemini chunks are covered by the plain-`str` branch (they don't emit
    Anthropic-style content-block lists for ordinary text), so this needs
    no per-provider branching despite running regardless of which of the
    three `AGENT_TOOLS`-bound models (see `agent/graph.py`) produced the
    chunk.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "") for block in content if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""


def _tool_message_content(output: Any) -> str:
    if hasattr(output, "content"):
        content = output.content
        return content if isinstance(content, str) else str(content)
    return str(output)


def _extract_tool_artifact(tool_name: str, output: Any) -> dict[str, Any]:
    """Every streamed tool (see `STREAMED_TOOL_NAMES`) uses
    `response_format="content_and_artifact"`, so a successful call always
    carries a structured `.artifact` dict alongside its LLM-facing text.
    Falls back to wrapping the plain text content if a tool short-circuited
    (e.g. raised) before reaching its `content_and_artifact` return —
    `compile_and_test_cpp` gets its own fallback shape so `ExecutionCard`
    still receives a well-formed (if error-only) result.
    """
    artifact = getattr(output, "artifact", None)
    if isinstance(artifact, dict):
        return artifact
    if tool_name == CPP_EXECUTION_TOOL:
        return build_cpp_execution_result(error_message=_tool_message_content(output))
    return {"error": _tool_message_content(output)}


def _missing_provider_key_message(exc: MissingProviderKeyError) -> str:
    """Clean, user-facing text for a `MissingProviderKeyError` — names the
    specific model the user selected and tells them exactly what to do,
    rather than a generic failure. Surfaced as a normal `token` event (not
    an HTTP error) since this fires mid-stream, after SSE headers are
    already flushed — see the module docstring on `stream_agent_reply`.
    """
    provider_label = exc.model.provider.value.title()
    return (
        f"Error: you've selected {exc.model.label}, but no {provider_label} API key is "
        f"saved for your account. Open Settings and add your {provider_label} API key "
        "(or pick a different model) to continue."
    )


async def stream_agent_reply(
    message: str,
    api_keys: dict[str, str],
    thread_id: str,
    default_model: str,
    codeforces_handle: str | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    """Runs `message` through the LangGraph CP coach agent, yielding stream
    events for the frontend SSE layer.

    Events are plain dicts with a `type` field:
    - `token`: `{"type": "token", "content": "<text chunk>"}`
    - `tool_start`: `{"type": "tool_start", "name": "<tool in STREAMED_TOOL_NAMES>"}`
    - `tool_end`: `{"type": "tool_end", "name": "...", "result": {...}}`

    `thread_id` scopes conversational memory: the checkpointer transparently
    loads this thread's prior `messages` state before the graph runs and
    persists the updated state (this turn's human message, any tool calls,
    and the final AI reply) afterwards — no history is passed explicitly.

    `api_keys` (a `{"anthropic"|"openai"|"google": "<key>"}` dict, see
    `services/profiles.py::UserProfile.api_keys`) and `default_model` flow
    in via `config.configurable` only, never as part of the graph
    input/state — see `agent/graph.py`'s module docstring for why that
    distinction is load-bearing, not stylistic. `default_model` is resolved
    to a provider up front (see `agent/models.py::resolve_model`) so a
    missing key for *that* provider is reported before the graph is ever
    invoked, rather than failing deep inside the agent<->tools loop.

    Streams transparently across tool calls: whichever agent turn ends up
    producing the final answer (with or without intermediate tool calls)
    has its tokens forwarded as they arrive. Never raises — API failures,
    an unrecognized/missing-key model selection, and `GraphRecursionError`
    (recursion_limit exceeded) are all caught and yielded as a user-visible
    error message instead of crashing the request.
    """
    try:
        model = resolve_model(default_model)
    except UnknownModelError as exc:
        yield {
            "type": "token",
            "content": f"Error: '{exc.model_id}' is not a supported model. Open Settings and pick one from the list.",
        }
        return

    if not api_keys.get(model.provider.value):
        yield {"type": "token", "content": _missing_provider_key_message(MissingProviderKeyError(model))}
        return

    graph = get_graph()
    inputs = {"messages": [HumanMessage(content=message)]}
    config = {
        "configurable": {
            "thread_id": thread_id,
            "api_keys": api_keys,
            "default_model": model.id,
            "codeforces_handle": codeforces_handle,
        },
        "recursion_limit": settings.agent_recursion_limit,
    }

    try:
        async for event in graph.astream_events(inputs, config=config, version="v2"):
            event_type = event.get("event")
            tool_name = event.get("name")

            if event_type == "on_chat_model_stream":
                chunk = event["data"]["chunk"]
                if not isinstance(chunk, AIMessageChunk):
                    continue
                text = _extract_text(chunk.content)
                if text:
                    yield {"type": "token", "content": text}
                continue

            if tool_name not in STREAMED_TOOL_NAMES:
                continue

            if event_type == "on_tool_start":
                yield {"type": "tool_start", "name": tool_name}
                continue

            if event_type == "on_tool_end":
                output = event["data"].get("output")
                result = _extract_tool_artifact(tool_name, output)
                yield {"type": "tool_end", "name": tool_name, "result": result}
    except GraphRecursionError:
        logger.warning("Agent hit recursion_limit=%d without finishing", settings.agent_recursion_limit)
        yield {
            "type": "token",
            "content": (
                "(The agent used too many tool calls without reaching a final answer — "
                "try rephrasing or asking a more specific question.)"
            ),
        }
    except MissingProviderKeyError as exc:
        # Defensive: the pre-flight check above should always catch this
        # first. Kept here too in case `_agent_node` ever raises it directly
        # (e.g. a future caller invokes the graph without going through the
        # pre-flight check), so it still surfaces as the clean message
        # rather than falling into the generic `except Exception` below.
        yield {"type": "token", "content": _missing_provider_key_message(exc)}
    except Exception as exc:
        logger.exception("Agent graph execution failed")
        yield {
            "type": "token",
            "content": f"(Sorry, something went wrong while generating a response: {exc})",
        }
