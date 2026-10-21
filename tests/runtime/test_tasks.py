import asyncio
from collections.abc import Awaitable, Callable

from investigator.domain.runs import TaskState
from investigator.runtime.budget import BudgetExceeded
from investigator.runtime.tasks import run_task
from investigator.tracing import MemoryTracer, TaskFinished, TaskStarted


def failing(times: int, error: Exception) -> Callable[[], Awaitable[str]]:
    calls = {"n": 0}

    async def run() -> str:
        calls["n"] += 1
        if calls["n"] <= times:
            raise error
        return "recovered"

    return run


async def test_a_failure_is_retried_and_both_attempts_are_traced() -> None:
    tracer = MemoryTracer()

    result = await run_task(
        "flaky",
        "observability",
        failing(1, ValueError("bad json")),
        tracer=tracer,
        timeout_s=1,
        max_attempts=2,
    )

    assert (result.state, result.attempts, result.value) == (TaskState.SUCCEEDED, 2, "recovered")
    assert [e.attempt for e in tracer.of_type(TaskStarted)] == [1, 2]
    assert [e.state for e in tracer.of_type(TaskFinished)] == [TaskState.SUCCEEDED]


async def test_a_timeout_counts_as_a_failure() -> None:
    async def hang() -> None:
        await asyncio.sleep(10)

    result = await run_task(
        "slow", "dependency", hang, tracer=MemoryTracer(), timeout_s=0.01, max_attempts=1
    )

    assert (result.state, result.error) == (TaskState.FAILED, "timed out after 0.01s")


async def test_the_last_error_is_kept_when_every_attempt_fails() -> None:
    result = await run_task(
        "broken",
        "critic",
        failing(5, ValueError("bad json")),
        tracer=MemoryTracer(),
        timeout_s=1,
        max_attempts=2,
    )

    assert (result.state, result.attempts, result.error) == (
        TaskState.FAILED,
        2,
        "ValueError: bad json",
    )


async def test_an_exhausted_budget_is_not_retried() -> None:
    result = await run_task(
        "agent",
        "reasoning",
        failing(1, BudgetExceeded("spent")),
        tracer=MemoryTracer(),
        timeout_s=1,
        max_attempts=3,
    )

    assert (result.state, result.attempts, result.error) == (TaskState.FAILED, 1, "spent")


async def test_nothing_starts_once_the_run_must_stop() -> None:
    started: list[str] = []
    tracer = MemoryTracer()

    async def job() -> None:
        started.append("late")

    result = await run_task(
        "late",
        "reporting",
        job,
        tracer=tracer,
        timeout_s=1,
        max_attempts=2,
        stop_reason=lambda: "budget fully spent",
    )

    assert (result.state, result.error) == (TaskState.CANCELLED, "budget fully spent")
    assert started == []
    assert tracer.of_type(TaskStarted) == []
