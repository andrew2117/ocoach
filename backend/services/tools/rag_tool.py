"""RAG tool: wraps the Phase 2 Qdrant `query_similar` search as a LangGraph tool.

Mirrors the retrieval behavior previously inlined in `routes/chat.py`
(Phase 2's `_retrieve_context`), but now exposed as a tool the agent calls
deliberately, rather than being unconditionally run before every reply.

Like Phase 2, embeddings always use `OPENAI_API_KEY` from the environment/
`.env` — never the caller's BYOK `X-API-Key`, which is for the Anthropic
chat model and may not even be an OpenAI key.

Phase 10: wrapped with `response_format="content_and_artifact"` so the
frontend can render the underlying retrieved chunks as a collapsible
`RAGCitationBadge` instead of only seeing them folded into the LLM's prose.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from core.config import settings
from services.vector_db import get_vector_db_service

logger = logging.getLogger(__name__)

RAG_TOOL_LIMIT = 4
SNIPPET_MAX_CHARS = 500

SearchCpKnowledgePayload = tuple[str, dict[str, Any]]


class SearchCpKnowledgeInput(BaseModel):
    query: str = Field(
        ...,
        min_length=1,
        description="Natural-language search query against the competitive-programming knowledge base.",
    )


def _error_payload(query: str, message: str) -> SearchCpKnowledgePayload:
    return message, {"query": query, "chunks": [], "error": message}


@tool(args_schema=SearchCpKnowledgeInput, response_format="content_and_artifact")
async def search_cp_knowledge(query: str) -> SearchCpKnowledgePayload:
    """Searches the competitive programming knowledge base (algorithm
    write-ups, editorials, technique notes) for content relevant to `query`.
    MANDATORY before explaining an advanced data structure or technique from
    memory — Segment Trees (incl. lazy propagation), Fenwick/BIT, Sparse
    Tables, Suffix Arrays/automata, HLD, centroid decomposition, and similar
    ICPC-literature staples — to ground the explanation in the coach's
    reference material before falling back to general knowledge.
    """
    api_key = settings.openai_api_key
    if not api_key:
        logger.warning("search_cp_knowledge tool skipped: OPENAI_API_KEY is not configured")
        return _error_payload(
            query, "Knowledge base search is unavailable: OPENAI_API_KEY is not configured on the server."
        )

    try:
        service = get_vector_db_service()
        chunks = await service.query_similar(query=query, api_key=api_key, limit=RAG_TOOL_LIMIT)
    except Exception as exc:
        logger.exception("search_cp_knowledge tool failed")
        return _error_payload(query, f"Knowledge base search failed: {exc}")

    if not chunks:
        return "No matching notes were found in the knowledge base for this query.", {
            "query": query,
            "chunks": [],
            "error": None,
        }

    structured: list[dict[str, Any]] = []
    lines = [f"Found {len(chunks)} relevant note(s):"]
    for chunk in chunks:
        snippet = " ".join(chunk["content"].split())
        if len(snippet) > SNIPPET_MAX_CHARS:
            snippet = snippet[:SNIPPET_MAX_CHARS].rstrip() + "..."
        topic = chunk.get("topic") or ""
        topic_label = f" ({topic})" if topic else ""
        lines.append(f"- [{chunk['source']}]{topic_label} {snippet}")
        structured.append(
            {
                "source": chunk.get("source", "unknown"),
                "topic": topic,
                "snippet": snippet,
                "score": chunk.get("score"),
            }
        )

    return "\n".join(lines), {"query": query, "chunks": structured, "error": None}
