"""Codeforces profile tool: surfaces a user's rating and weak topics.

Combines two public Codeforces endpoints — `user.info` (rating/rank) and
`user.status` (submission history) — behind the shared rate-limited client
in `codeforces_client.py`, and summarizes which problem tags most often
show up on submissions verdicted `WRONG_ANSWER` or `TIME_LIMIT_EXCEEDED`,
so the coach agent can point the user at concrete topics to drill.

Phase 10: wrapped with `response_format="content_and_artifact"` so the
frontend can render a `CodeforcesStatsCard` from the structured artifact
instead of only seeing the LLM's prose summary, and memoized for
`STATS_CACHE_TTL_SECONDS` per handle (Codeforces' 5 req/s cap makes
re-fetching on every "how am I doing" follow-up in a conversation wasteful
and risks tripping the limit).
"""

from __future__ import annotations

import asyncio
from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from services.tools.cache import async_ttl_cache
from services.tools.codeforces_client import codeforces_get

SUBMISSIONS_COUNT = 50
FAILURE_VERDICTS = {"WRONG_ANSWER", "TIME_LIMIT_EXCEEDED"}
TOP_TAGS_LIMIT = 5
STATS_CACHE_TTL_SECONDS = 300  # 5 minutes
STATS_CACHE_MAXSIZE = 512

CodeforcesStatsPayload = tuple[str, dict[str, Any]]


class GetUserStatsInput(BaseModel):
    """Strict schema: `handle` is mandatory — a call with no handle is a
    malformed call from the LLM, not something to silently paper over.
    """

    handle: str = Field(
        ...,
        min_length=1,
        description="The Codeforces username (handle) to look up, e.g. 'tourist'.",
    )


def _weak_tags(submissions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tag_failures: dict[str, int] = {}
    for submission in submissions:
        if submission.get("verdict") not in FAILURE_VERDICTS:
            continue
        for tag in submission.get("problem", {}).get("tags", []):
            tag_failures[tag] = tag_failures.get(tag, 0) + 1

    ranked = sorted(tag_failures.items(), key=lambda item: item[1], reverse=True)[:TOP_TAGS_LIMIT]
    return [{"tag": tag, "count": count} for tag, count in ranked]


def _error_payload(handle: str, message: str) -> CodeforcesStatsPayload:
    return message, {
        "handle": handle,
        "rating": None,
        "max_rating": None,
        "rank": None,
        "max_rank": None,
        "submissions_analyzed": 0,
        "weak_tags": [],
        "error": message,
    }


@async_ttl_cache(maxsize=STATS_CACHE_MAXSIZE, ttl_seconds=STATS_CACHE_TTL_SECONDS)
async def _fetch_user_stats(handle: str) -> CodeforcesStatsPayload:
    """Cached core: fetches profile info + recent submissions concurrently
    (both still funnel through the shared rate limiter in
    `codeforces_client`, so this never exceeds 5 req/s even though it fires
    two requests at once) and builds the (text, artifact) tool payload.
    """
    info_response, status_response = await asyncio.gather(
        codeforces_get(
            "user.info", {"handles": handle}, context=f"fetching profile info for handle '{handle}'"
        ),
        codeforces_get(
            "user.status",
            {"handle": handle, "from": 1, "count": SUBMISSIONS_COUNT},
            context=f"fetching submissions for handle '{handle}'",
        ),
    )

    if not info_response.ok:
        return _error_payload(handle, info_response.error or "Unknown Codeforces API error.")
    if not status_response.ok:
        return _error_payload(handle, status_response.error or "Unknown Codeforces API error.")

    info_result = info_response.result or []
    if not info_result:
        return _error_payload(handle, f"Codeforces handle '{handle}' was not found.")
    profile = info_result[0]

    submissions = status_response.result or []
    weak_tags = _weak_tags(submissions)
    rating = profile.get("rating")
    rank = profile.get("rank")

    artifact = {
        "handle": profile.get("handle", handle),
        "rating": rating,
        "max_rating": profile.get("maxRating"),
        "rank": rank,
        "max_rank": profile.get("maxRank"),
        "submissions_analyzed": len(submissions),
        "weak_tags": weak_tags,
        "error": None,
    }

    rating_label = str(rating) if rating is not None else "unrated"
    rank_label = rank or "unranked"

    if not submissions:
        text = f"'{handle}' (rating {rating_label}, {rank_label}) has no recent submissions to analyze."
    elif not weak_tags:
        text = (
            f"'{handle}' (rating {rating_label}, {rank_label}) has no WRONG_ANSWER or "
            f"TIME_LIMIT_EXCEEDED verdicts in their last {len(submissions)} submissions — "
            "no clear weak topics detected."
        )
    else:
        summary = ", ".join(f"{t['tag']} ({t['count']} failure(s))" for t in weak_tags)
        text = (
            f"'{handle}' is rated {rating_label} ({rank_label}). Weak topics from their last "
            f"{len(submissions)} submissions (tags with frequent WRONG_ANSWER/TIME_LIMIT_EXCEEDED "
            f"verdicts): {summary}"
        )

    return text, artifact


@tool(args_schema=GetUserStatsInput, response_format="content_and_artifact")
async def get_user_stats(handle: str) -> CodeforcesStatsPayload:
    """Fetches a Codeforces user's current rating/rank and last 50
    submissions, summarizing which problem tags most frequently end in a
    WRONG_ANSWER or TIME_LIMIT_EXCEEDED verdict. Call this proactively
    whenever the user asks for tailored practice advice, mentions
    weaknesses or recurring mistakes, or asks what to study next, and their
    Codeforces handle is known — don't wait for them to describe their own
    weak spots. Results are cached for 5 minutes per handle.
    """
    handle = (handle or "").strip()
    if not handle:
        return _error_payload("", "No Codeforces handle was provided, so user stats are unavailable.")
    return await _fetch_user_stats(handle)
