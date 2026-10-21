"""What a tool call ends in: a result, or one of the failures that become an error result."""

from typing import Any

from investigator.domain.base import DomainModel
from investigator.domain.tools import ErrorKind, ToolStatus


class ToolError(DomainModel):
    kind: ErrorKind
    message: str
    retryable: bool


class ToolResult(DomainModel):
    """The outcome of one tool call, after validation, retries and caching."""

    call_id: str
    tool: str
    arguments: dict[str, Any]
    status: ToolStatus
    output: dict[str, Any] | None = None
    artifacts: tuple[str, ...] = ()
    notices: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    error: ToolError | None = None
    attempts: int
    duration_ms: float
    cached: bool = False


class ToolFailure(Exception):
    """A tool call that did not produce a result."""

    kind = ErrorKind.INTERNAL
    retry_after_s: float | None = None


class ToolTimeout(ToolFailure):
    kind = ErrorKind.TIMEOUT


class BackendUnavailable(ToolFailure):
    kind = ErrorKind.UNAVAILABLE


class RateLimited(ToolFailure):
    kind = ErrorKind.RATE_LIMITED

    def __init__(self, message: str, retry_after_s: float) -> None:
        super().__init__(message)
        self.retry_after_s = retry_after_s


class CallRefused(ToolFailure):
    kind = ErrorKind.REFUSED


class InvalidQuery(ToolFailure):
    """The arguments cannot be answered as given. The caller should fix them, not retry."""

    kind = ErrorKind.INVALID_QUERY
