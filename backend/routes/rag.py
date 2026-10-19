"""RAG routes: direct similarity search against the Qdrant knowledge base.

Useful for testing/debugging retrieval independently of the chat endpoint.
Phase 7: requires Supabase JWT auth (same as chat/sessions) and uses the
server-side `OPENAI_API_KEY` — not a caller-supplied `X-API-Key`.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException

from core.config import settings
from core.security import AuthenticatedUser, get_current_user
from models.rag import RagSearchRequest, RagSearchResponse, RetrievedChunk
from services.vector_db import get_vector_db_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/rag", tags=["rag"])


@router.post("/search", response_model=RagSearchResponse)
async def search(
    payload: RagSearchRequest,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Embeds `query` and returns the top-`limit` most similar knowledge base chunks.

    Requires a valid Supabase session. Embeddings use the server-side
    `OPENAI_API_KEY` (same as the agent's `search_cp_knowledge` tool).

    Returns an empty `results` list (not an error) if the knowledge base is
    empty — see `services/vector_db.py::query_similar`.
    """
    if not settings.openai_api_key:
        raise HTTPException(
            status_code=503,
            detail="Knowledge base search is unavailable: OPENAI_API_KEY is not configured on the server.",
        )

    service = get_vector_db_service()
    try:
        results = await service.query_similar(
            payload.query, api_key=settings.openai_api_key, limit=payload.limit
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("RAG search failed for authenticated user_id=%s", user.user_id)
        raise HTTPException(status_code=502, detail=f"Retrieval failed: {exc}") from exc

    return RagSearchResponse(results=[RetrievedChunk(**r) for r in results])
