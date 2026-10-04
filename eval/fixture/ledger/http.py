from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

Transport = Callable[[str], bytes]


class TransientError(Exception):
    """A failure worth retrying (timeout, 5xx)."""


@dataclass(frozen=True)
class RetryPolicy:
    attempts: int = 5
    base_delay: float = 0.5
    max_delay: float = 8.0

    def delays(self) -> list[float]:
        """Sleep before each retry: exponential, capped."""
        return [min(self.base_delay * 2**i, self.max_delay) for i in range(self.attempts - 1)]


{{WHY:retry}}
class Client:
    def __init__(
        self,
        transport: Transport,
        policy: RetryPolicy = RetryPolicy(),
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.transport = transport
        self.policy = policy
        self.sleep = sleep

    def get(self, url: str) -> bytes:
        delays = self.policy.delays()
        for attempt in range(self.policy.attempts):
            try:
                return self.transport(url)
            except TransientError:
                if attempt == self.policy.attempts - 1:
                    raise
                self.sleep(delays[attempt])
        raise AssertionError("unreachable")


def legacy_retry(fn: Callable[[], bytes], tries: int = 3, delay: float = 1.0,
                 sleep: Callable[[float], None] = time.sleep) -> bytes:
    """Fixed-delay retry."""
    for i in range(tries):
        try:
            return fn()
        except TransientError:
            if i == tries - 1:
                raise
            sleep(delay)
    raise AssertionError("unreachable")
