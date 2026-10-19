"""Ingestion CLI: chunk documents under `backend/data/raw/` and push them into
the Qdrant `cp_knowledge` collection.

Supported source formats: `.md`, `.txt`, `.pdf`.

Usage (run from `backend/`, with the venv activated):

    python -m scripts.ingest --api-key sk-...
    OPENAI_API_KEY=sk-... python -m scripts.ingest

Important: Qdrant's local mode holds an exclusive lock on `qdrant_data/`, so
stop the API server (`uvicorn main:app`) before running this script when
`QDRANT_HOST` is unset. With `QDRANT_HOST` set, ingestion talks to the Qdrant
server and can run while the API is up.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any, Callable

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from langchain_text_splitters import (  # noqa: E402
    MarkdownTextSplitter,
    RecursiveCharacterTextSplitter,
)
from pypdf import PdfReader  # noqa: E402

from core.config import settings  # noqa: E402
from services.vector_db import get_vector_db_service  # noqa: E402

RAW_DATA_DIR = BACKEND_ROOT / "data" / "raw"
CHUNK_SIZE_TOKENS = 1000
CHUNK_OVERLAP_TOKENS = 150
CHARS_PER_TOKEN_FALLBACK = 4  # used only if tiktoken can't load (e.g. offline)
SUPPORTED_SUFFIXES = {".md", ".txt", ".pdf"}


def _token_length_function() -> Callable[[str], int]:
    """Returns a token-counting function, falling back to a char heuristic
    if `tiktoken` isn't installed or can't fetch its encoding (e.g. offline).
    """
    try:
        import tiktoken

        encoding = tiktoken.get_encoding("cl100k_base")
        return lambda text: len(encoding.encode(text))
    except Exception:
        print(
            "  (tiktoken unavailable/offline — approximating token counts "
            f"as chars / {CHARS_PER_TOKEN_FALLBACK})"
        )
        return lambda text: max(1, len(text) // CHARS_PER_TOKEN_FALLBACK)


def _make_splitter(is_markdown: bool, length_function: Callable[[str], int]):
    """Builds a splitter that tries to keep code blocks and logical sections
    intact by preferring to break on markdown/paragraph boundaries before
    falling back to sentence/word/char boundaries.
    """
    if is_markdown:
        # MarkdownTextSplitter's built-in separators already prioritize
        # headings and ```-fenced code blocks over mid-paragraph breaks.
        return MarkdownTextSplitter(
            chunk_size=CHUNK_SIZE_TOKENS,
            chunk_overlap=CHUNK_OVERLAP_TOKENS,
            length_function=length_function,
        )

    return RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE_TOKENS,
        chunk_overlap=CHUNK_OVERLAP_TOKENS,
        length_function=length_function,
        separators=["\n\n", "\n", ". ", " ", ""],
    )


def _load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _load_pdf(path: Path) -> str:
    reader = PdfReader(str(path))
    return "\n\n".join(page.extract_text() or "" for page in reader.pages)


def chunk_document(text: str, source: str, length_function: Callable[[str], int]) -> list[dict[str, Any]]:
    is_markdown = source.lower().endswith(".md")
    splitter = _make_splitter(is_markdown, length_function)
    topic = Path(source).stem.replace("_", " ").replace("-", " ").title()
    return [
        {"content": chunk, "source": source, "topic": topic}
        for chunk in splitter.split_text(text)
        if chunk.strip()
    ]


def collect_chunks(raw_dir: Path, length_function: Callable[[str], int]) -> list[dict[str, Any]]:
    all_chunks: list[dict[str, Any]] = []
    for path in sorted(raw_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue

        rel_source = str(path.relative_to(raw_dir))
        try:
            text = _load_pdf(path) if path.suffix.lower() == ".pdf" else _load_text(path)
        except Exception as exc:
            print(f"  skipping {rel_source}: failed to read ({exc})")
            continue

        if not text.strip():
            print(f"  skipping {rel_source}: no extractable text")
            continue

        chunks = chunk_document(text, rel_source, length_function)
        print(f"  {rel_source}: {len(chunks)} chunk(s)")
        all_chunks.extend(chunks)

    return all_chunks


async def run_ingestion(api_key: str, raw_dir: Path = RAW_DATA_DIR) -> int:
    if not raw_dir.exists():
        print(f"Raw data directory not found: {raw_dir}")
        return 0

    print(f"Scanning {raw_dir} for {sorted(SUPPORTED_SUFFIXES)} files...")
    length_function = _token_length_function()
    chunks = collect_chunks(raw_dir, length_function)

    if not chunks:
        print("No documents found to ingest.")
        return 0

    print(f"Embedding and upserting {len(chunks)} chunk(s) into '{settings.qdrant_collection}'...")
    service = get_vector_db_service()
    inserted = await service.insert_documents(chunks, api_key=api_key)
    print(f"Done. Inserted {inserted} chunk(s).")
    return inserted


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest documents into the Qdrant knowledge base.")
    parser.add_argument(
        "--api-key",
        default=None,
        help="OpenAI API key (defaults to OPENAI_API_KEY env var / .env)",
    )
    parser.add_argument(
        "--raw-dir",
        default=None,
        help="Override the source directory (defaults to backend/data/raw)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    api_key = args.api_key or settings.openai_api_key
    if not api_key:
        print("Error: provide --api-key or set OPENAI_API_KEY (env var / .env).")
        raise SystemExit(1)

    raw_dir = Path(args.raw_dir).resolve() if args.raw_dir else RAW_DATA_DIR
    asyncio.run(run_ingestion(api_key, raw_dir))


if __name__ == "__main__":
    main()
