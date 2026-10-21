"""Retries, timeouts, caching and failure handling around every tool call."""

import pytest

from investigator.domain.tools import ErrorKind, ToolName, ToolStatus
from investigator.tools.executor import RetryPolicy, ToolExecutor
from investigator.tools.faults import RETRY_AFTER_S
from investigator.tools.logs import LogQuery, LogQueryResult
from investigator.tools.registry import ToolRegistry
from investigator.tools.results import BackendUnavailable
from investigator.tracing import MemoryTracer, ToolAttempted

from .conftest import RecordingSleep, ToolsFactory, at, fault

CHANGES = {"start": at("08:00"), "end": at("11:00")}


def executor_for(
    registry: ToolRegistry, tracer: MemoryTracer, sleep: RecordingSleep
) -> ToolExecutor:
    return ToolExecutor(registry, tracer=tracer, timeout_s=0.05, sleep=sleep)


async def test_a_timeout_is_retried_and_the_second_attempt_succeeds(
    tools: ToolsFactory, tracer: MemoryTracer, sleep: RecordingSleep
) -> None:
    registry = tools(fault(tool="get_change_history", kind="timeout", invocations=[1]))
    result = await executor_for(registry, tracer, sleep).execute("get_change_history", CHANGES)

    assert result.status is ToolStatus.OK
    assert result.attempts == 2
    assert [e.outcome for e in tracer.of_type(ToolAttempted)] == ["timeout", "ok"]
    assert len(sleep.delays) == 1


async def test_a_persistent_outage_gives_up_after_the_retry_budget(
    tools: ToolsFactory, tracer: MemoryTracer, sleep: RecordingSleep
) -> None:
    registry = tools(fault(tool="get_change_history", kind="unavailable"))
    result = await executor_for(registry, tracer, sleep).execute("get_change_history", CHANGES)

    assert result.status is ToolStatus.ERROR
    assert result.error is not None
    assert result.error.kind is ErrorKind.UNAVAILABLE
    assert result.error.retryable
    assert result.attempts == RetryPolicy().max_attempts
    assert len(sleep.delays) == RetryPolicy().max_attempts - 1


async def test_rate_limits_wait_at_least_as_long_as_the_backend_asks(
    tools: ToolsFactory, tracer: MemoryTracer, sleep: RecordingSleep
) -> None:
    registry = tools(fault(tool="get_change_history", kind="rate_limited", invocations=[1, 2]))
    result = await executor_for(registry, tracer, sleep).execute("get_change_history", CHANGES)

    assert result.attempts == 3
    assert all(delay >= RETRY_AFTER_S for delay in sleep.delays)


@pytest.mark.parametrize("attempt", [1, 2, 3, 6])
def test_backoff_is_bounded_by_the_policy(attempt: int) -> None:
    policy = RetryPolicy(base_delay_s=0.25, max_delay_s=1.0)
    assert (
        0
        <= policy.delay_s(BackendUnavailable("down"), attempt)
        <= min(1.0, 0.25 * 2 ** (attempt - 1))
    )


async def test_invalid_arguments_fail_without_calling_the_tool(
    executor: ToolExecutor, tracer: MemoryTracer
) -> None:
    result = await executor.execute(
        "query_logs", {"service": "payments-service", "start": "yesterday"}
    )

    assert result.error is not None
    assert result.error.kind is ErrorKind.INVALID_QUERY
    assert "start" in result.error.message
    assert "end: Field required" in result.error.message
    assert result.attempts == 0
    assert tracer.of_type(ToolAttempted) == []


async def test_unknown_tools_are_named_back_with_the_available_ones(executor: ToolExecutor) -> None:
    result = await executor.execute("query_traces", {})

    assert result.error is not None
    assert "available tools: query_logs" in result.error.message


async def test_identical_successful_calls_are_served_from_cache(
    executor: ToolExecutor, tracer: MemoryTracer
) -> None:
    first = await executor.execute("get_change_history", CHANGES)
    second = await executor.execute("get_change_history", dict(reversed(list(CHANGES.items()))))

    assert not first.cached
    assert second.cached
    assert second.output == first.output
    assert second.call_id != first.call_id
    assert len(tracer.of_type(ToolAttempted)) == 1


async def test_failed_calls_are_not_cached(
    tools: ToolsFactory, tracer: MemoryTracer, sleep: RecordingSleep
) -> None:
    registry = tools(fault(tool="get_change_history", kind="unavailable", invocations=[1, 2, 3]))
    executor = executor_for(registry, tracer, sleep)

    first = await executor.execute("get_change_history", CHANGES)
    second = await executor.execute("get_change_history", CHANGES)

    assert first.status is ToolStatus.ERROR
    assert second.status is ToolStatus.OK
    assert not second.cached


async def test_a_bug_in_a_tool_becomes_an_internal_error_not_a_crash(tracer: MemoryTracer) -> None:
    class Broken:
        name = ToolName.QUERY_LOGS
        description = "always fails"
        args_model = LogQuery

        async def run(self, args: LogQuery) -> LogQueryResult:
            raise RuntimeError("index out of range")

    result = await ToolExecutor(ToolRegistry([Broken()]), tracer=tracer).execute(
        "query_logs", {"service": "payments-service", "start": at("10:00"), "end": at("10:10")}
    )

    assert result.error is not None
    assert result.error.kind is ErrorKind.INTERNAL
    assert "index out of range" in result.error.message
    assert result.attempts == 1


async def test_a_backend_that_keeps_failing_is_not_called_again(
    tools: ToolsFactory, tracer: MemoryTracer, sleep: RecordingSleep
) -> None:
    registry = tools(fault(tool="get_change_history", kind="unavailable"))
    executor = executor_for(registry, tracer, sleep)

    results = [
        await executor.execute("get_change_history", {**CHANGES, "kinds": [kind]})
        for kind in ("deploy", "config", "infra")
    ]

    assert [r.attempts for r in results] == [3, 3, 0]
    assert results[2].error is not None
    assert results[2].error.kind is ErrorKind.REFUSED
    assert "treated as down" in results[2].error.message
    assert not results[2].error.retryable


async def test_a_success_closes_the_circuit_again(
    tools: ToolsFactory, tracer: MemoryTracer, sleep: RecordingSleep
) -> None:
    registry = tools(fault(tool="get_change_history", kind="unavailable", invocations=[1, 2, 3]))
    executor = executor_for(registry, tracer, sleep)

    failed = await executor.execute("get_change_history", {**CHANGES, "kinds": ["deploy"]})
    recovered = await executor.execute("get_change_history", {**CHANGES, "kinds": ["config"]})
    after = await executor.execute("get_change_history", {**CHANGES, "kinds": ["infra"]})

    assert failed.status is ToolStatus.ERROR
    assert recovered.status is ToolStatus.OK
    assert after.status is ToolStatus.OK
