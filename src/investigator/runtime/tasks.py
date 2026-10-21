"""Running one agent's piece of work with a time limit and a second chance.

The LangGraph graphs decide what runs and in what order. This is what each step does
around an agent: try it, give up after a while, and report a failure as a result rather
than an exception, so one failed agent becomes missing evidence instead of a crash.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from investigator.domain.runs import TaskState
from investigator.runtime.budget import BudgetExceeded
from investigator.tracing import TaskFinished, TaskStarted, Tracer


@dataclass(frozen=True)
class TaskResult:
    task_id: str
    state: TaskState
    value: Any = None
    error: str | None = None
    attempts: int = 0


async def run_task(
    task_id: str,
    label: str,
    job: Callable[[], Awaitable[Any]],
    *,
    tracer: Tracer,
    timeout_s: float,
    max_attempts: int,
    stop_reason: Callable[[], str | None] = lambda: None,
) -> TaskResult:
    """Run ``job`` up to ``max_attempts`` times; a spent budget is never retried."""
    if (reason := stop_reason()) is not None:
        return TaskResult(task_id, TaskState.CANCELLED, error=reason)
    error = ""
    for attempt in range(1, max_attempts + 1):
        tracer.record(TaskStarted(task_id=task_id, label=label, attempt=attempt))
        try:
            value = await asyncio.wait_for(job(), timeout_s)
        except TimeoutError:
            error = f"timed out after {timeout_s:g}s"
        except BudgetExceeded as exc:
            failed = TaskResult(task_id, TaskState.FAILED, error=str(exc), attempts=attempt)
            return _finished(tracer, label, failed)
        except Exception as exc:  # Any agent failure is recoverable at this level.
            error = f"{type(exc).__name__}: {exc}"
        else:
            done = TaskResult(task_id, TaskState.SUCCEEDED, value, attempts=attempt)
            return _finished(tracer, label, done)
    failed = TaskResult(task_id, TaskState.FAILED, error=error, attempts=max_attempts)
    return _finished(tracer, label, failed)


def _finished(tracer: Tracer, label: str, result: TaskResult) -> TaskResult:
    tracer.record(
        TaskFinished(
            task_id=result.task_id,
            label=label,
            state=result.state,
            attempts=result.attempts,
            error=result.error,
        )
    )
    return result
