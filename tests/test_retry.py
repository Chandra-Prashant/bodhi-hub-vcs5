"""
Retry tests.

Written after a real-key run returned 503 UNAVAILABLE. The classification
tests matter most: retrying a bad API key wastes four seconds and still fails,
while not retrying an overloaded model sends a document to manual entry for no
reason.
"""

from __future__ import annotations

import pytest

from app.services.retry import is_transient, with_retry


class Boom(Exception):
    pass


# --- what is worth retrying -----------------------------------------------

@pytest.mark.parametrize("message", [
    "503 UNAVAILABLE. This model is currently experiencing high demand.",
    "429 RESOURCE_EXHAUSTED",
    "Rate limit exceeded",
    "500 Internal error",
    "504 Deadline exceeded",
    "Connection reset by peer",
    "The model is overloaded",
])
def test_transient_failures_are_retried(message):
    assert is_transient(Boom(message))


@pytest.mark.parametrize("message", [
    "400 INVALID_ARGUMENT",
    "401 Unauthorized",
    "403 PERMISSION_DENIED",
    "404 model not found",
    "API key not valid. Please pass a valid API key.",
    "Billing has not been enabled for this project",
])
def test_permanent_failures_are_not_retried(message):
    """Retrying a wrong key burns the backoff and fails identically."""
    assert not is_transient(Boom(message))


def test_a_permanent_marker_wins_over_a_transient_one():
    """'quota exceeded' on a billing-disabled project reads as retryable and
    is not."""
    assert not is_transient(Boom("429 quota exceeded — billing not enabled"))


def test_an_unrecognised_error_is_not_retried():
    """Unknown failures are treated as permanent. Retrying something we do not
    understand risks repeating a side effect."""
    assert not is_transient(Boom("something entirely unexpected"))


# --- behaviour -------------------------------------------------------------

def test_a_successful_call_is_not_retried():
    calls = []

    def call():
        calls.append(1)
        return "ok"

    assert with_retry(call, sleep=lambda _: None) == "ok"
    assert len(calls) == 1


def test_a_transient_failure_is_retried_then_succeeds():
    attempts = []

    def call():
        attempts.append(1)
        if len(attempts) < 3:
            raise Boom("503 UNAVAILABLE high demand")
        return "ok"

    assert with_retry(call, sleep=lambda _: None) == "ok"
    assert len(attempts) == 3


def test_a_permanent_failure_raises_immediately():
    attempts = []

    def call():
        attempts.append(1)
        raise Boom("401 API key not valid")

    with pytest.raises(Boom):
        with_retry(call, sleep=lambda _: None)
    assert len(attempts) == 1


def test_the_original_error_survives_exhaustion():
    """The caller must see the real reason, not 'retries exhausted'."""
    def call():
        raise Boom("503 UNAVAILABLE high demand")

    with pytest.raises(Boom, match="high demand"):
        with_retry(call, attempts=2, sleep=lambda _: None)


def test_attempts_are_capped():
    attempts = []

    def call():
        attempts.append(1)
        raise Boom("503 unavailable")

    with pytest.raises(Boom):
        with_retry(call, attempts=3, sleep=lambda _: None)
    assert len(attempts) == 3


def test_backoff_grows():
    delays = []

    def call():
        raise Boom("503 unavailable")

    with pytest.raises(Boom):
        with_retry(call, attempts=4, base_delay=1.0, sleep=delays.append)
    assert len(delays) == 3
    assert delays[0] < delays[1] < delays[2]


def test_jitter_keeps_concurrent_callers_apart():
    """Several documents uploaded together would otherwise retry in lockstep
    and hit the same overloaded model at the same instant."""
    seen = set()
    for _ in range(20):
        delays = []

        def call():
            raise Boom("503 unavailable")

        with pytest.raises(Boom):
            with_retry(call, attempts=2, base_delay=1.0, sleep=delays.append)
        seen.add(round(delays[0], 6))
    assert len(seen) > 1


def test_the_retry_hook_is_called():
    events = []

    def call():
        if len(events) < 1:
            raise Boom("503 unavailable")
        return "ok"

    with_retry(call, sleep=lambda _: None,
               on_retry=lambda n, exc, d: events.append((n, d)))
    assert events and events[0][0] == 1
