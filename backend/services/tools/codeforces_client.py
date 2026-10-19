"""Shared Codeforces API client: process-wide rate limiting and uniform
error handling for `codeforces_tool.py`, `contest_tool.py`, and
`agent/tools.generate_practice_contest`.

Codeforces enforces an undocumented-but-well-known cap of ~5 requests per
second per client; exceeding it does NOT raise an HTTP error — it returns
HTTP 200 with `{"status": "FAILED", "comment": "Call limit exceeded"}` in
the body, so it must be detected by inspecting the parsed payload, not by
catching `httpx.HTTPStatusError`. This module centralizes that check plus
the transport-level error handling both tools previously duplicated, and
adds a shared rate limiter so concurrent tool invocations from a single
agent turn (e.g. the LLM calling `get_user_stats` and
`get_upcoming_contests` in the same tool-call batch) can never collectively
exceed the limit.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

CODEFORCES_API_BASE = "https://codeforces.com/api"
REQUEST_TIMEOUT_SECONDS = 10.0

# Codeforces' well-known cap; enforced here as a rolling window rather than
# a fixed per-second bucket so bursts are smoothed rather than allowed to
# spike to 5 at the top of every wall-clock second.
_RATE_LIMIT_MAX_CALLS = 5
_RATE_LIMIT_WINDOW_SECONDS = 1.0

RATE_LIMIT_FALLBACK_MESSAGE = (
    "Codeforces is temporarily rate-limiting this server (it allows at most 5 requests/second). "
    "Please ask again in a few seconds rather than retrying immediately."
)


class _AsyncRateLimiter:
    """Rolling-window limiter: at most `max_calls` acquisitions per
    `window_seconds`, shared process-wide across every Codeforces endpoint.

    A plain `asyncio.Lock` + timestamp deque is sufficient here — this is a
    single FastAPI worker process, not a multi-worker/multi-replica
    deployment (which would need a shared store, e.g. Redis, instead).
    """

    def __init__(self, max_calls: int, window_seconds: float) -> None:
        self._max_calls = max_calls
        self._window_seconds = window_seconds
        self._timestamps: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                while self._timestamps and now - self._timestamps[0] >= self._window_seconds:
                    self._timestamps.popleft()
                if len(self._timestamps) < self._max_calls:
                    self._timestamps.append(now)
                    return
                sleep_for = self._window_seconds - (now - self._timestamps[0])
                await asyncio.sleep(max(sleep_for, 0.01))


_RATE_LIMITER = _AsyncRateLimiter(_RATE_LIMIT_MAX_CALLS, _RATE_LIMIT_WINDOW_SECONDS)


@dataclass(frozen=True)
class CodeforcesResponse:
    """Uniform result of a Codeforces API call: exactly one of `result`
    (on success) or `error` (an already-worded, LLM-safe message) is set.
    Callers never need their own try/except around this — every failure
    mode (timeout, transport error, non-JSON body, `status != "OK"`,
    including a rate-limit hit) is normalized into `error` here.
    """

    ok: bool
    result: Any = None
    error: str | None = None


def _is_rate_limited(comment: str) -> bool:
    return "call limit exceeded" in comment.lower()


async def codeforces_get(endpoint: str, params: dict[str, Any], *, context: str) -> CodeforcesResponse:
    """GETs `{CODEFORCES_API_BASE}/{endpoint}`, rate-limited to 5 req/s
    process-wide via `_RATE_LIMITER`.

    `context` is a short human-readable phrase (e.g. "fetching stats for
    handle 'tourist'") spliced into any error message, so the same helper
    produces naturally-worded errors regardless of which tool called it.
    """
    await _RATE_LIMITER.acquire()

    url = f"{CODEFORCES_API_BASE}/{endpoint}"
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
    except httpx.TimeoutException:
        return CodeforcesResponse(ok=False, error=f"Codeforces API request timed out while {context}.")
    except httpx.HTTPStatusError as exc:
        return CodeforcesResponse(
            ok=False,
            error=f"Codeforces API returned an error ({exc.response.status_code}) while {context}.",
        )
    except httpx.HTTPError as exc:
        return CodeforcesResponse(ok=False, error=f"Codeforces API request failed while {context}: {exc}")
    except ValueError:
        return CodeforcesResponse(
            ok=False, error=f"Codeforces API returned an unparseable response while {context}."
        )

    if payload.get("status") != "OK":
        comment = str(payload.get("comment", "unknown error"))
        if _is_rate_limited(comment):
            logger.warning("Codeforces API rate limit hit while %s", context)
            return CodeforcesResponse(ok=False, error=RATE_LIMIT_FALLBACK_MESSAGE)
        return CodeforcesResponse(ok=False, error=f"Codeforces API error while {context}: {comment}")

    return CodeforcesResponse(ok=True, result=payload.get("result"))
