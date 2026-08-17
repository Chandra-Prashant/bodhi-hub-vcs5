"""
Retrying transient model failures.

Found during the first run against a real key: Gemini returned

    503 UNAVAILABLE — This model is currently experiencing high demand.

Without retries that marks a document FAILED and routes it to manual entry —
a field auditor retyping a form because a shared service was busy for four
seconds. Rate limits (429) behave the same way and are more common in
production than in testing, because production has concurrent users.

The distinction that matters is transient versus permanent. A 401 means the key
is wrong and retrying wastes time; a 400 means the request is malformed and
will be malformed again. Only overload, rate limiting and network faults are
worth another attempt, so those are the only ones retried — and after the last
attempt the original failure is raised unchanged, so the caller still sees the
real reason rather than "retries exhausted".
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")

MAX_ATTEMPTS = 4
BASE_DELAY = 1.0
MAX_DELAY = 20.0

# Substrings identifying a failure worth retrying. Matched against the string
# form of the exception because the SDK raises several classes for what is, to
# a caller, the same condition.
_TRANSIENT_MARKERS = (
    "503", "unavailable", "high demand", "overloaded",
    "429", "resource_exhausted", "rate limit", "quota exceeded",
    "500", "internal error", "504", "deadline", "timeout",
    "connection reset", "connection aborted", "temporarily",
)

# Substrings that mean retrying cannot help. Checked first, because "quota
# exceeded" for a billing-disabled project contains a retryable marker while
# being entirely permanent.
_PERMANENT_MARKERS = (
    "api key not valid", "api_key_invalid", "permission denied",
    "401", "403", "billing", "not found", "404",
    "invalid argument", "400",
)


def is_transient(exc: BaseException) -> bool:
    text = f"{type(exc).__name__}: {exc}".lower()
    if any(marker in text for marker in _PERMANENT_MARKERS):
        return False
    return any(marker in text for marker in _TRANSIENT_MARKERS)


def with_retry(
    call: Callable[[], T],
    *,
    attempts: int = MAX_ATTEMPTS,
    base_delay: float = BASE_DELAY,
    sleep: Callable[[float], None] = time.sleep,
    on_retry: Callable[[int, BaseException, float], None] | None = None,
) -> T:
    """Call `call`, retrying only transient failures with exponential backoff.

    Jitter is added because several documents uploaded together would otherwise
    retry in lockstep and hit the same overloaded model at the same instant.
    """
    last: BaseException | None = None

    for attempt in range(1, attempts + 1):
        try:
            return call()
        except BaseException as exc:  # noqa: BLE001 — re-raised below
            last = exc
            if not is_transient(exc) or attempt == attempts:
                raise
            delay = min(base_delay * (2 ** (attempt - 1)), MAX_DELAY)
            delay += random.uniform(0, delay * 0.25)
            if on_retry is not None:
                on_retry(attempt, exc, delay)
            sleep(delay)

    # Unreachable: the loop either returns or raises.
    raise last if last else RuntimeError("with_retry made no attempts")
