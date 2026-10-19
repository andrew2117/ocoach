"""Vector database service: Qdrant storage + OpenAI embeddings for RAG.

Local dev uses Qdrant's embedded mode (`QdrantClient(path=...)`), which
persists under `backend/qdrant_data`. That mode takes an exclusive file lock,
so only one process may open it. Stop the API before `scripts/ingest.py`.

Production sets `QDRANT_HOST` (the `qdrant` service in
`docker-compose.prod.yml`). The client then talks to the Qdrant REST API,
which is safe with multiple uvicorn workers and with ingestion while the
API is up.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels
from qdrant_client.http.exceptions import UnexpectedResponse

from core.config import settings

logger = logging.getLogger(__name__)

VECTOR_SIZE = 1536  # text-embedding-3-small's native size; -3-large is truncated to match via `dimensions=`
DEFAULT_BATCH_SIZE = 64

BACKEND_ROOT = Path(__file__).resolve().parent.parent


class VectorDBService:
    """Wraps a Qdrant collection and OpenAI embeddings for RAG."""

    def __init__(
        self,
        storage_path: str | Path | None = None,
        collection_name: str | None = None,
        embedding_model: str | None = None,
    ) -> None:
        self._collection_name = collection_name or settings.qdrant_collection
        self._embedding_model = embedding_model or settings.openai_embedding_model
        self._client = self._build_client(storage_path)
        self._ensure_collection()

    def _build_client(self, storage_path: str | Path | None) -> QdrantClient:
        """Remote server when `QDRANT_HOST` is set; embedded files otherwise.

        An explicit `storage_path` always selects local mode so callers and
        tests can open a private directory even if the process env points at
        a server.
        """
        host = settings.qdrant_host.strip()
        if storage_path is None and host:
            client_kwargs: dict[str, Any] = {
                "host": host,
                "port": settings.qdrant_port,
                "https": settings.qdrant_https,
                "timeout": settings.qdrant_timeout,
                "prefer_grpc": False,
            }
            if settings.qdrant_api_key:
                client_kwargs["api_key"] = settings.qdrant_api_key
            logger.info("Connecting to Qdrant at %s:%s", host, settings.qdrant_port)
            return QdrantClient(**client_kwargs)

        path = Path(storage_path or settings.qdrant_path)
        if not path.is_absolute():
            path = BACKEND_ROOT / path
        path.mkdir(parents=True, exist_ok=True)
        logger.info("Opening local Qdrant at %s", path)
        return QdrantClient(path=str(path))

    def _ensure_collection(self) -> None:
        """Creates the collection if it doesn't already exist (idempotent)."""
        existing = {c.name for c in self._client.get_collections().collections}
        if self._collection_name in existing:
            return
        self._client.create_collection(
            collection_name=self._collection_name,
            vectors_config=qmodels.VectorParams(
                size=VECTOR_SIZE,
                distance=qmodels.Distance.COSINE,
            ),
        )

    async def _embed(self, texts: list[str], api_key: str) -> list[list[float]]:
        """Embeds a batch of texts via the OpenAI API (async, non-blocking)."""
        if not api_key:
            raise ValueError("An OpenAI API key is required to generate embeddings.")
        client = AsyncOpenAI(api_key=api_key)
        response = await client.embeddings.create(
            model=self._embedding_model,
            input=texts,
            dimensions=VECTOR_SIZE,
        )
        return [item.embedding for item in response.data]

    async def insert_documents(
        self,
        chunks: list[dict[str, Any]],
        api_key: str,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> int:
        """Embeds and upserts a list of chunk dicts (each needs a "content" key).

        Any extra keys (e.g. `source`, `topic`) are stored as payload metadata
        alongside the embedded `content`. Runs in batches to keep individual
        OpenAI requests small and avoid holding huge lists of vectors in memory.

        Returns the number of chunks inserted.
        """
        if not chunks:
            return 0

        inserted = 0
        for start in range(0, len(chunks), batch_size):
            batch = chunks[start : start + batch_size]
            texts = [str(chunk["content"]) for chunk in batch]
            embeddings = await self._embed(texts, api_key)

            points = [
                qmodels.PointStruct(
                    id=str(uuid.uuid4()),
                    vector=embedding,
                    payload={
                        "content": chunk["content"],
                        "source": chunk.get("source", "unknown"),
                        "topic": chunk.get("topic", ""),
                    },
                )
                for chunk, embedding in zip(batch, embeddings)
            ]

            await asyncio.to_thread(
                self._client.upsert,
                collection_name=self._collection_name,
                points=points,
            )
            inserted += len(points)

        return inserted

    async def query_similar(
        self,
        query: str,
        api_key: str,
        limit: int = 4,
    ) -> list[dict[str, Any]]:
        """Embeds `query` and returns the top-`limit` most similar chunks.

        Returns an empty list (rather than raising) if the collection doesn't
        exist yet or is empty, so callers can treat "no knowledge base" as a
        normal, non-fatal state.
        """
        try:
            count = await asyncio.to_thread(
                self._client.count,
                collection_name=self._collection_name,
                exact=True,
            )
        except (UnexpectedResponse, ValueError) as exc:
            logger.warning("Vector DB collection %r unavailable: %s", self._collection_name, exc)
            return []

        if count.count == 0:
            return []

        (query_vector,) = await self._embed([query], api_key)

        result = await asyncio.to_thread(
            self._client.query_points,
            collection_name=self._collection_name,
            query=query_vector,
            limit=limit,
        )

        return [
            {
                "content": point.payload.get("content", "") if point.payload else "",
                "source": point.payload.get("source", "unknown") if point.payload else "unknown",
                "topic": point.payload.get("topic", "") if point.payload else "",
                "score": point.score,
            }
            for point in result.points
        ]


@lru_cache(maxsize=1)
def get_vector_db_service() -> VectorDBService:
    """Process-wide singleton.

    Local mode holds an exclusive file lock, so there must be one client per
    process. Remote mode has no lock; each uvicorn worker still keeps its own
    cached client.
    """
    return VectorDBService()
