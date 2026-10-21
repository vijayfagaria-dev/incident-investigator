"""Vocabulary for how a run executed: model calls, tasks and agents."""

from enum import StrEnum


class FinishReason(StrEnum):
    STOP = "stop"
    TOOL_CALLS = "tool_calls"
    LENGTH = "length"
    CONTENT_FILTER = "content_filter"
    OTHER = "other"


class TaskState(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    """A required dependency did not succeed."""
    CANCELLED = "cancelled"
    """The run was stopped before or while the task ran."""


class StopReason(StrEnum):
    """Why an agent stopped using tools and concluded."""

    CONCLUDED = "concluded"
    STEP_LIMIT = "step_limit"
    BUDGET = "budget"
