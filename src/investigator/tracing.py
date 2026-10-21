"""Structured events describing what happened during a run, for debugging and for metrics."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import AwareDatetime, Field

from investigator.domain.base import DomainModel
from investigator.domain.runs import FinishReason, TaskState
from investigator.domain.tools import ErrorKind, ToolStatus


class TraceEvent(DomainModel):
    at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))


class ToolAttempted(TraceEvent):
    event: Literal["tool_attempt"] = "tool_attempt"
    call_id: str
    tool: str
    """The name the caller asked for, which may not be a real tool."""
    attempt: int
    outcome: ToolStatus | ErrorKind
    duration_ms: float


class ToolCallFinished(TraceEvent):
    event: Literal["tool_call"] = "tool_call"
    call_id: str
    tool: str
    caller: str | None = None
    """The agent role that made the call, when known."""
    arguments: dict[str, Any] = Field(default_factory=dict)
    status: ToolStatus
    attempts: int
    cached: bool
    duration_ms: float
    artifacts: tuple[str, ...] = ()
    """Ids the call returned, which agents may cite."""


class ModelCalled(TraceEvent):
    event: Literal["model_call"] = "model_call"
    purpose: str
    """Who asked: an agent role, or another caller such as a smoke test."""
    model: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float
    rate_limit_wait_ms: float
    finish_reason: FinishReason | None
    tool_calls: int
    error: str | None = None


class ModelFellBack(TraceEvent):
    """The main model still failed after its retries, so the request went to the backup."""

    event: Literal["model_fallback"] = "model_fallback"
    purpose: str
    failed_model: str
    backup_model: str
    error: str


class TaskStarted(TraceEvent):
    event: Literal["task_start"] = "task_start"
    task_id: str
    label: str
    attempt: int


class TaskFinished(TraceEvent):
    event: Literal["task_finish"] = "task_finish"
    task_id: str
    label: str
    state: TaskState
    attempts: int
    error: str | None = None


class AgentCommitted(TraceEvent):
    """An agent's structured output, and what the board accepted from it."""

    event: Literal["agent_commit"] = "agent_commit"
    task_id: str
    role: str
    output: dict[str, Any]
    accepted: tuple[str, ...] = ()
    problems: tuple[str, ...] = ()
    error: str | None = None


class Standing(DomainModel):
    """One hypothesis as a round closed: how it ranked and what the critic made of it."""

    hypothesis_id: str
    version: int
    service: str
    category: str
    trigger: str | None
    stated_confidence: float
    confidence: float
    """After calibration; the ranking uses this."""
    verdict: str | None
    blocking_objections: int


class RoundEnded(TraceEvent):
    event: Literal["round_end"] = "round_end"
    round: int
    standings: tuple[Standing, ...]
    """Most confident first."""
    stop_reason: str | None
    """Why the investigation stopped after this round, or None if it went on."""


class Tracer(Protocol):
    def record(self, event: TraceEvent) -> None: ...


class MemoryTracer:
    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    def record(self, event: TraceEvent) -> None:
        self.events.append(event)

    def of_type[E: TraceEvent](self, kind: type[E]) -> list[E]:
        return [event for event in self.events if isinstance(event, kind)]


class JsonlTracer:
    """Appends each event as one JSON line, so a crashed run still leaves its trace."""

    def __init__(self, path: Path) -> None:
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, event: TraceEvent) -> None:
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(event.model_dump_json() + "\n")
