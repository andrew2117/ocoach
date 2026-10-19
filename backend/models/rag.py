"""Pydantic request/response models for the RAG search endpoint."""

from pydantic import BaseModel, Field


class RagSearchRequest(BaseModel):
    """Body payload for POST /api/rag/search.

    Requires a valid Supabase session (`Authorization: Bearer <token>`).
    Embeddings use the server-side `OPENAI_API_KEY` (same as the agent's
    `search_cp_knowledge` tool) — not a caller-supplied key.
    """

    query: str = Field(..., min_length=1, description="Text to search the knowledge base for")
    limit: int = Field(default=4, ge=1, le=20, description="Max number of chunks to return")


class RetrievedChunk(BaseModel):
    content: str
    source: str
    topic: str = ""
    score: float


class RagSearchResponse(BaseModel):
    results: list[RetrievedChunk]
