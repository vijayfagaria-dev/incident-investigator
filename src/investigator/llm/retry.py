"""Retries model calls that failed for reasons that pass: rate limits, timeouts, outages."""

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from random import Random

from investigator.llm.gateway import ModelError, ModelGateway, ModelRateLimited
from investigator.llm.messages import ChatRequest, ChatResponse


@dataclass(frozen=True)
class Backoff:
    attempts: int = 5
    first_delay_s: float = 5.0
    multiplier: float = 3.0
    max_delay_s: float = 60.0
    jitter: float = 0.2
    """Each delay varies by up to this fraction, so paused callers do not resume in step."""

    def delay(self, retry: int, rng: Random) -> float:
        """Seconds to wait before retry number ``retry`` (1-based)."""
        base = min(self.max_delay_s, self.first_delay_s * self.multiplier ** (retry - 1))
        return base * (1 + self.jitter * (2 * rng.random() - 1))


class Cooldown:
    """A pause shared by every caller of one endpoint once it rate-limits any of them."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._clock = clock
        self._sleep = sleep
        self._resume_at = 0.0

    def extend(self, seconds: float) -> None:
        self._resume_at = max(self._resume_at, self._clock() + seconds)

    async def wait(self) -> None:
        while (pause := self._resume_at - self._clock()) > 0:
            await self._sleep(pause)


class RetryingGateway:
    """Retries retryable model errors with exponential backoff.

    A shared free endpoint that answers 429 to one agent will answer 429 to the others as
    well, so a rate limit starts a cooldown every caller sharing it waits out, not just the
    one that hit it. Other retryable errors only delay the call that failed.
    """

    def __init__(
        self,
        inner: ModelGateway,
        backoff: Backoff | None = None,
        *,
        cooldown: Cooldown | None = None,
        rng: Random | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._inner = inner
        self._backoff = backoff or Backoff()
        self._cooldown = cooldown or Cooldown(clock=clock, sleep=sleep)
        self._rng = rng or Random()
        self._sleep = sleep

    async def complete(self, request: ChatRequest) -> ChatResponse:
        retry = 0
        while True:
            await self._cooldown.wait()
            try:
                return await self._inner.complete(request)
            except ModelError as error:
                retry += 1
                if not error.retryable or retry >= self._backoff.attempts:
                    raise
                delay = self._backoff.delay(retry, self._rng)
                if isinstance(error, ModelRateLimited):
                    self._cooldown.extend(delay)
                else:
                    await self._sleep(delay)
