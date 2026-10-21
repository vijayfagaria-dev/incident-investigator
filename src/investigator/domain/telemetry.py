"""Records the simulated platform produces and the tools return."""

from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from investigator.domain.artifacts import ArtifactId, dependency_id
from investigator.domain.base import DomainModel
from investigator.domain.causes import RootCause


class TimeWindow(DomainModel):
    start: AwareDatetime
    end: AwareDatetime

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.end <= self.start:
            raise ValueError("window end must be after its start")
        return self

    def contains(self, ts: datetime) -> bool:
        return self.start <= ts < self.end

    def minutes(self) -> list[datetime]:
        count = int((self.end - self.start).total_seconds() // 60)
        return [self.start + timedelta(minutes=i) for i in range(count)]


class LogLevel(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"

    def at_least(self, other: "LogLevel") -> bool:
        return _SEVERITY[self] >= _SEVERITY[other]


_SEVERITY = {LogLevel.DEBUG: 0, LogLevel.INFO: 1, LogLevel.WARN: 2, LogLevel.ERROR: 3}


class LogRecord(DomainModel):
    id: ArtifactId
    ts: AwareDatetime
    service: str
    pod: str
    az: str
    level: LogLevel
    message: str
    template: str
    """The message before field substitution; stands in for a log-pattern clusterer."""
    trace_id: str | None = None
    attrs: dict[str, str | int | float] = Field(default_factory=dict)


class MetricSeries(DomainModel):
    """One metric for one service at a fixed step, starting at ``start``."""

    id: ArtifactId
    service: str
    name: str
    unit: str
    start: AwareDatetime
    step_seconds: int = 60
    values: tuple[float, ...]

    def timestamps(self) -> list[datetime]:
        step = timedelta(seconds=self.step_seconds)
        return [self.start + i * step for i in range(len(self.values))]


class ChangeKind(StrEnum):
    DEPLOY = "deploy"
    CONFIG = "config"
    FEATURE_FLAG = "feature_flag"
    SECRET_ROTATION = "secret_rotation"
    INFRA = "infra"


class ChangeEvent(DomainModel):
    id: ArtifactId
    ts: AwareDatetime
    service: str
    kind: ChangeKind
    actor: str
    summary: str
    details: dict[str, str] = Field(default_factory=dict)


CallProtocol = Literal["http", "https", "grpc", "sql", "redis", "kafka"]
Criticality = Literal["hard", "soft"]


class DependencyEdge(DomainModel):
    """``source`` calls ``target``. A hard dependency fails the caller when it fails."""

    source: str
    target: str
    protocol: CallProtocol
    criticality: Criticality
    timeout_ms: int | None = None

    @property
    def id(self) -> str:
        return dependency_id(self.source, self.target)


class PastIncident(DomainModel):
    """A postmortem from before the incident under investigation."""

    id: ArtifactId
    date: date
    title: str
    services: tuple[str, ...]
    symptoms: tuple[str, ...]
    root_cause: RootCause
    summary: str
    resolution: str
