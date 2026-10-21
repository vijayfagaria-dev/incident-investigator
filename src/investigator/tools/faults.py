"""Tools that fail the way a scenario says their backends do: timeouts, outages, rate limits."""

import asyncio
from collections.abc import Iterable
from typing import Any

from investigator.tools.base import Tool, ToolOutput
from investigator.tools.results import BackendUnavailable, RateLimited
from investigator.world.scenario import FaultKind, ToolFault

TRANSIENT_KINDS = (FaultKind.TIMEOUT, FaultKind.UNAVAILABLE, FaultKind.RATE_LIMITED)
HANG_S = 3600.0
"""How long a timed-out backend hangs; the caller's timeout always cuts it short."""
RETRY_AFTER_S = 0.5


class FaultInjectingTool:
    """Wraps a tool so that the invocations the scenario names fail.

    Invocations are counted per tool and include retries, so a fault on invocations 1 and 2
    makes the first call succeed on its third attempt.
    """

    def __init__(self, inner: Tool, faults: Iterable[ToolFault]) -> None:
        self.name = inner.name
        self.description = inner.description
        self.args_model = inner.args_model
        self._inner = inner
        self._faults = [f for f in faults if f.tool is inner.name and f.kind in TRANSIENT_KINDS]
        self._invocations = 0

    async def run(self, args: Any) -> ToolOutput:
        self._invocations += 1
        fault = self._scheduled_fault()
        if fault is FaultKind.TIMEOUT:
            await asyncio.sleep(HANG_S)
        elif fault is FaultKind.UNAVAILABLE:
            raise BackendUnavailable(f"{self.name} backend returned 503 Service Unavailable")
        elif fault is FaultKind.RATE_LIMITED:
            raise RateLimited(
                f"{self.name} backend returned 429 Too Many Requests", retry_after_s=RETRY_AFTER_S
            )
        return await self._inner.run(args)

    def _scheduled_fault(self) -> FaultKind | None:
        for fault in self._faults:
            if fault.applies_to(self._invocations):
                return fault.kind
        return None
