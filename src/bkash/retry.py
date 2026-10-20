"""Exponential backoff with full jitter for transient failures (5xx, timeouts, network)."""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, field

import httpx

RETRYABLE_STATUS: frozenset[int] = frozenset({500, 502, 503, 504})


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay: float = 0.5
    max_delay: float = 8.0
    jitter: bool = True
    retry_statuses: frozenset[int] = RETRYABLE_STATUS
    rng: Callable[[], float] = field(default=random.random, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.base_delay < 0 or self.max_delay < 0:
            raise ValueError("delays cannot be negative")

    @classmethod
    def none(cls) -> RetryPolicy:
        return cls(max_attempts=1)

    def delay_for(self, attempt: int) -> float:
        """Delay before the retry that follows `attempt` (1-based): base * 2^(attempt-1), capped."""
        capped = float(min(self.max_delay, self.base_delay * float(2 ** (attempt - 1))))
        if not self.jitter:
            return capped
        return capped * self.rng()

    def should_retry_response(self, response: httpx.Response) -> bool:
        return response.status_code in self.retry_statuses

    @staticmethod
    def should_retry_exception(exc: Exception) -> bool:
        return isinstance(exc, httpx.TimeoutException | httpx.NetworkError)

    def can_retry(self, attempt: int) -> bool:
        return attempt < self.max_attempts
