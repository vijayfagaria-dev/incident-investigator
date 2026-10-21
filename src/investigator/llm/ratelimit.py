import asyncio
import time
from collections import deque
from collections.abc import Awaitable, Callable

WINDOW_S = 60.0


class RateLimiter:
    """Allows at most ``per_minute`` request starts in any 60-second window.

    Shared by every caller of one provider, so concurrent agents queue here instead of
    collecting 429s. It limits how often requests start, not how many are in flight.
    """

    def __init__(
        self,
        per_minute: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._capacity = max(1, int(per_minute))
        self._clock = clock
        self._sleep = sleep
        self._starts: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> float:
        """Wait for a slot and return how long the caller waited, in seconds."""
        async with self._lock:
            requested = self._clock()
            while True:
                now = self._clock()
                while self._starts and now - self._starts[0] >= WINDOW_S:
                    self._starts.popleft()
                if len(self._starts) < self._capacity:
                    self._starts.append(now)
                    return now - requested
                await self._sleep(WINDOW_S - (now - self._starts[0]))
