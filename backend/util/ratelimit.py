"""Rate-limit retry with exponential backoff + jitter.

Shared by the generation providers (FAL, Gemini image, Gemini TTS, ElevenLabs)
so transient 429 / quota / 503 errors are retried instead of failing the job.
Non-rate-limit errors (e.g. 401 auth, 400 bad request) raise immediately so we
don't waste time retrying unrecoverable calls.
"""

import asyncio
import random
import time

_MARKERS = (
    "429", "rate limit", "rate_limit", "resource_exhausted", "too many requests",
    "quota", "503", "unavailable", "overloaded", "try again",
)


def is_rate_limit(exc: Exception) -> bool:
    s = str(exc).lower()
    return any(m in s for m in _MARKERS)


def _delay(i: int, base: float, max_delay: float) -> float:
    return min(max_delay, base * (2 ** i)) + random.uniform(0, 1)


async def aretry(fn, *, attempts: int = 5, base: float = 2.0, max_delay: float = 60.0):
    """Await fn() with exponential backoff on rate-limit errors."""
    last = None
    for i in range(attempts):
        try:
            return await fn()
        except Exception as e:  # noqa: BLE001
            last = e
            if not is_rate_limit(e) or i == attempts - 1:
                raise
            await asyncio.sleep(_delay(i, base, max_delay))
    raise last  # pragma: no cover


def retry(fn, *, attempts: int = 5, base: float = 2.0, max_delay: float = 60.0):
    """Call fn() (sync) with exponential backoff on rate-limit errors."""
    last = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            last = e
            if not is_rate_limit(e) or i == attempts - 1:
                raise
            time.sleep(_delay(i, base, max_delay))
    raise last  # pragma: no cover
