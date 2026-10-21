import asyncio
import json
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable, Collection, Mapping
from dataclasses import dataclass, field
from random import Random
from typing import Any

from pydantic import ValidationError

from investigator.domain.tools import ToolStatus
from investigator.tools.base import Tool, ToolArgs, ToolOutput
from investigator.tools.registry import ToolRegistry
from investigator.tools.results import (
    CallRefused,
    InvalidQuery,
    ToolError,
    ToolFailure,
    ToolResult,
    ToolTimeout,
)
from investigator.tracing import MemoryTracer, ToolAttempted, ToolCallFinished, Tracer

Sleep = Callable[[float], Awaitable[None]]


@dataclass(frozen=True)
class RetryPolicy:
    """Bounded retries with full-jitter exponential backoff."""

    max_attempts: int = 3
    base_delay_s: float = 0.25
    max_delay_s: float = 4.0
    rng: Random = field(default_factory=lambda: Random(0), compare=False)

    def should_retry(self, failure: ToolFailure, attempt: int) -> bool:
        return failure.kind.retryable and attempt < self.max_attempts

    def delay_s(self, failure: ToolFailure, attempt: int) -> float:
        """Never shorter than a delay the backend asked for (``Retry-After``)."""
        ceiling = min(self.max_delay_s, self.base_delay_s * 2 ** (attempt - 1))
        return max(self.rng.uniform(0, ceiling), failure.retry_after_s or 0.0)


class CircuitBreaker:
    """Stops calling a backend for the rest of a run once two calls in a row have failed.

    Only calls that used up their retries on a retryable failure count; any successful or
    partial answer resets the count.
    """

    THRESHOLD = 2

    def __init__(self) -> None:
        self._failures: dict[str, int] = defaultdict(int)

    def is_open(self, tool: str) -> bool:
        return self._failures[tool] >= self.THRESHOLD

    def failures(self, tool: str) -> int:
        return self._failures[tool]

    def record(self, result: ToolResult) -> None:
        if result.status is not ToolStatus.ERROR:
            self._failures[result.tool] = 0
        elif result.error is not None and result.error.kind.retryable:
            self._failures[result.tool] += 1


class ToolExecutor:
    """Runs tool calls with validation, a timeout per attempt, bounded retries and caching.

    It never raises because a tool failed: every call ends in a ``ToolResult``, so a failing
    backend degrades an investigation instead of crashing it.
    """

    def __init__(
        self,
        registry: ToolRegistry,
        *,
        tracer: Tracer | None = None,
        timeout_s: float = 10.0,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self.registry = registry
        self._tracer = tracer or MemoryTracer()
        self._timeout_s = timeout_s
        self._sleep = sleep
        self._policy = RetryPolicy()
        self._breaker = CircuitBreaker()
        self._cache: dict[tuple[str, str], ToolResult] = {}
        self._calls = 0

    async def execute(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
        allowed: Collection[str] | None = None,
        caller: str | None = None,
    ) -> ToolResult:
        """Run a call. ``allowed`` restricts which tools ``caller`` may use."""
        call_id = self._next_call_id()
        started = time.monotonic()

        tool = self.registry.get(tool_name)
        if tool is None or (allowed is not None and tool_name not in allowed):
            known = ", ".join(n for n in self.registry.names() if allowed is None or n in allowed)
            failure = InvalidQuery(f"unknown tool {tool_name!r}; available tools: {known}")
            return self._to_result(call_id, tool_name, dict(arguments), failure, 0, started, caller)
        try:
            args = tool.args_model.model_validate(arguments)
        except ValidationError as exc:
            failure = InvalidQuery(_validation_message(exc))
            return self._to_result(call_id, tool_name, dict(arguments), failure, 0, started, caller)

        canonical = args.model_dump(mode="json")
        key = (tool_name, json.dumps(canonical, sort_keys=True))
        if key in self._cache:
            result = self._cache[key].model_copy(
                update={"call_id": call_id, "cached": True, "duration_ms": 0.0}
            )
            self._trace_call(result, caller)
            return result

        if self._breaker.is_open(tool_name):
            refusal = CallRefused(
                f"{tool_name} has failed {self._breaker.failures(tool_name)} calls in a row; "
                "its backend is treated as down for the rest of this investigation"
            )
            return self._to_result(call_id, tool_name, canonical, refusal, 0, started, caller)

        outcome, attempts = await self._run_with_retries(call_id, tool, args)
        result = self._to_result(call_id, tool_name, canonical, outcome, attempts, started, caller)
        self._breaker.record(result)
        if result.status is not ToolStatus.ERROR:
            self._cache[key] = result
        return result

    def reject(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
        failure: ToolFailure,
        caller: str | None = None,
    ) -> ToolResult:
        """Record a call refused before reaching the tool, e.g. malformed arguments or no budget."""
        return self._to_result(
            self._next_call_id(), tool_name, dict(arguments), failure, 0, time.monotonic(), caller
        )

    def _next_call_id(self) -> str:
        self._calls += 1
        return f"call-{self._calls:04d}"

    async def _run_with_retries(
        self, call_id: str, tool: Tool, args: ToolArgs
    ) -> tuple[ToolOutput | ToolFailure, int]:
        attempt = 1
        while True:
            started = time.monotonic()
            outcome = await self._run_once(tool, args)
            label = outcome.kind if isinstance(outcome, ToolFailure) else _status(outcome)
            self._tracer.record(
                ToolAttempted(
                    call_id=call_id,
                    tool=tool.name,
                    attempt=attempt,
                    outcome=label,
                    duration_ms=_elapsed_ms(started),
                )
            )
            if isinstance(outcome, ToolOutput):
                return outcome, attempt
            if not self._policy.should_retry(outcome, attempt):
                return outcome, attempt
            await self._sleep(self._policy.delay_s(outcome, attempt))
            attempt += 1

    async def _run_once(self, tool: Tool, args: ToolArgs) -> ToolOutput | ToolFailure:
        try:
            return await asyncio.wait_for(tool.run(args), self._timeout_s)
        except TimeoutError:
            return ToolTimeout(f"{tool.name} did not respond within {self._timeout_s:g}s")
        except ToolFailure as failure:
            return failure
        except Exception as exc:  # A bug in a tool must not take the investigation down.
            return ToolFailure(f"{tool.name} failed unexpectedly: {exc!r}")

    def _to_result(
        self,
        call_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        outcome: ToolOutput | ToolFailure,
        attempts: int,
        started: float,
        caller: str | None = None,
    ) -> ToolResult:
        common = {
            "call_id": call_id,
            "tool": tool_name,
            "arguments": arguments,
            "attempts": attempts,
            "duration_ms": _elapsed_ms(started),
        }
        if isinstance(outcome, ToolFailure):
            error = ToolError(
                kind=outcome.kind, message=str(outcome), retryable=outcome.kind.retryable
            )
            result = ToolResult(**common, status=ToolStatus.ERROR, error=error)
        else:
            result = ToolResult(
                **common,
                status=_status(outcome),
                output=outcome.model_dump(mode="json", exclude={"notices", "warnings"}),
                artifacts=outcome.artifacts(),
                notices=outcome.notices,
                warnings=outcome.warnings,
            )
        self._trace_call(result, caller)
        return result

    def _trace_call(self, result: ToolResult, caller: str | None) -> None:
        self._tracer.record(
            ToolCallFinished(
                call_id=result.call_id,
                tool=result.tool,
                caller=caller,
                arguments=result.arguments,
                status=result.status,
                attempts=result.attempts,
                cached=result.cached,
                duration_ms=result.duration_ms,
                artifacts=result.artifacts,
            )
        )


def _status(output: ToolOutput) -> ToolStatus:
    return ToolStatus.PARTIAL if output.notices else ToolStatus.OK


def _elapsed_ms(started: float) -> float:
    return round((time.monotonic() - started) * 1000, 2)


def _validation_message(error: ValidationError) -> str:
    problems = []
    for issue in error.errors():
        where = ".".join(str(part) for part in issue["loc"]) or "arguments"
        problems.append(f"{where}: {issue['msg']}")
    return "invalid arguments: " + "; ".join(problems)
