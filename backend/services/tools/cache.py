"""Async TTL memoization for read-mostly, rate-limited external API calls.

`cachetools.TTLCache` is a synchronous `MutableMapping` — safe to use as the
backing store here (no I/O happens on the dict itself) — but a naive
`if key in cache: ... else: await fn(); cache[key] = result` dance has a
well-known cache-stampede race: N concurrent callers all miss and all hit
the real endpoint at once. `async_ttl_cache` closes that race with a
per-key `asyncio.Lock`, so e.g. ten simultaneous `get_upcoming_contests`
tool calls (from ten concurrent chat requests) result in exactly one
Codeforces API call, not ten.
"""

from __future__ import annotations

import asyncio
import functools
from collections.abc import Awaitable, Callable, Hashable
from typing import Any, TypeVar

from cachetools import TTLCache

T = TypeVar("T")

_SENTINEL = object()


def _cache_key(args: tuple[Any, ...], kwargs: dict[str, Any]) -> Hashable:
    return (args, tuple(sorted(kwargs.items())))


def async_ttl_cache(
    *, maxsize: int, ttl_seconds: float
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """Decorator factory: memoizes an async function's result for
    `ttl_seconds`, keyed on its call args/kwargs (must be hashable — true
    for the plain `str` handles/queries these tools take).
    """

    def decorator(fn: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        cache: TTLCache = TTLCache(maxsize=maxsize, ttl=ttl_seconds)
        locks: dict[Hashable, asyncio.Lock] = {}
        locks_guard = asyncio.Lock()

        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            key = _cache_key(args, kwargs)

            cached = cache.get(key, _SENTINEL)
            if cached is not _SENTINEL:
                return cached  # type: ignore[return-value]

            # Per-key lock, created lazily and never removed — bounded by
            # `maxsize` distinct keys ever seen, acceptable for the small,
            # bounded key spaces (handles, static no-arg calls) these
            # tools use.
            async with locks_guard:
                lock = locks.setdefault(key, asyncio.Lock())

            async with lock:
                cached = cache.get(key, _SENTINEL)
                if cached is not _SENTINEL:
                    return cached  # type: ignore[return-value]

                result = await fn(*args, **kwargs)
                cache[key] = result
                return result

        return wrapper

    return decorator
