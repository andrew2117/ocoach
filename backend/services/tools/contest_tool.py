"""Codeforces contest-schedule tool: lists upcoming contests.

Uses the public Codeforces `contest.list` endpoint (gym contests excluded)
rather than CLIST, since it needs no API key and already covers Codeforces
round scheduling, which is the primary use case for this coach. Calls go
through the shared rate-limited client in `codeforces_client.py`.

Phase 10: wrapped with `response_format="content_and_artifact"` so the
frontend can render a `CodeforcesStatsCard` from the structured contest
list, and memoized for `CONTESTS_CACHE_TTL_SECONDS` process-wide (the
schedule changes far less often than the agent might be asked about it, and
this endpoint takes no arguments, so a single cache entry serves every
caller).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel

from services.tools.cache import async_ttl_cache
from services.tools.codeforces_client import codeforces_get

UPCOMING_CONTESTS_LIMIT = 5
CONTESTS_CACHE_TTL_SECONDS = 3600  # 1 hour
CONTESTS_CACHE_MAXSIZE = 1  # single no-arg cache entry

CodeforcesContestsPayload = tuple[str, dict[str, Any]]


class GetUpcomingContestsInput(BaseModel):
    """`get_upcoming_contests` takes no arguments. Kept as an explicit empty
    schema (rather than omitting `args_schema`) so every tool in this
    package declares its input contract the same way.
    """


def _error_payload(message: str) -> CodeforcesContestsPayload:
    return message, {"contests": [], "error": message}


@async_ttl_cache(maxsize=CONTESTS_CACHE_MAXSIZE, ttl_seconds=CONTESTS_CACHE_TTL_SECONDS)
async def _fetch_upcoming_contests() -> CodeforcesContestsPayload:
    response = await codeforces_get("contest.list", {"gym": "false"}, context="fetching the contest list")
    if not response.ok:
        return _error_payload(response.error or "Unknown Codeforces API error.")

    contests = [c for c in (response.result or []) if c.get("phase") == "BEFORE"]
    contests.sort(key=lambda c: c.get("startTimeSeconds", 0))
    contests = contests[:UPCOMING_CONTESTS_LIMIT]

    if not contests:
        return "No upcoming Codeforces contests were found.", {"contests": [], "error": None}

    structured: list[dict[str, Any]] = []
    lines = ["Upcoming Codeforces contests:"]
    for contest in contests:
        name = contest.get("name", "Unknown contest")
        start_seconds = contest.get("startTimeSeconds")
        duration_hours = round(contest.get("durationSeconds", 0) / 3600, 1)

        if start_seconds is not None:
            start_dt = datetime.fromtimestamp(start_seconds, tz=timezone.utc)
            start_iso = start_dt.isoformat()
            start_label = start_dt.strftime("%Y-%m-%d %H:%M UTC")
        else:
            start_iso = None
            start_label = "unknown start time"

        lines.append(f"- {name}: starts {start_label}, duration {duration_hours:.1f}h")
        structured.append(
            {
                "id": contest.get("id"),
                "name": name,
                "start_time_iso": start_iso,
                "duration_hours": duration_hours,
            }
        )

    return "\n".join(lines), {"contests": structured, "error": None}


@tool(args_schema=GetUpcomingContestsInput, response_format="content_and_artifact")
async def get_upcoming_contests() -> CodeforcesContestsPayload:
    """Fetches the next scheduled Codeforces contests, including each
    contest's name, start time (UTC), and duration. Use this when the user
    asks what contests are coming up or wants help planning practice around
    an upcoming round. Cached for 1 hour.
    """
    return await _fetch_upcoming_contests()
