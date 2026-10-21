"""Declarative description of one incident: what changed and how the telemetry reacted."""

from datetime import datetime
from enum import StrEnum
from random import Random
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from investigator.domain.base import DomainModel
from investigator.domain.telemetry import ChangeEvent, LogLevel, TimeWindow
from investigator.domain.tools import ToolName
from investigator.world.topology import FieldSpec, Topology


class Shape(StrEnum):
    """How quickly an effect reaches its target."""

    STEP = "step"
    RAMP = "ramp"

    def progress(self, minutes_elapsed: int, ramp_minutes: int) -> float:
        """Fraction of the way to the target, counting the first affected minute as 1."""
        if self is Shape.RAMP:
            return min(1.0, minutes_elapsed / ramp_minutes)
        return 1.0


class _TimedEffect(DomainModel):
    service: str
    start: AwareDatetime
    end: AwareDatetime | None = None

    def first_minute(self) -> datetime:
        return self.start.replace(second=0, microsecond=0)

    def covers_minute(self, minute: datetime) -> bool:
        return self.first_minute() <= minute and (self.end is None or minute < self.end)


class MetricEffect(_TimedEffect):
    """Moves a metric towards a target from ``start`` until ``end``.

    The target is either an absolute value (``to``) or a multiple of the normal value
    (``factor``). A ramp reaches it after ``ramp_minutes``; a step reaches it at once.
    """

    kind: Literal["metric"]
    metric: str
    shape: Shape = Shape.STEP
    ramp_minutes: int = Field(default=5, ge=1)
    to: float | None = None
    factor: float | None = Field(default=None, gt=0)
    noise: float | None = Field(default=None, ge=0)
    """Relative noise around an absolute target; defaults to the metric's own noise."""

    @model_validator(mode="after")
    def _one_target(self) -> Self:
        if (self.to is None) == (self.factor is None):
            raise ValueError(f"{self.service}/{self.metric}: set exactly one of 'to' or 'factor'")
        return self

    def target(self, normal: float, default_noise: float, rng: Random) -> float:
        if self.factor is not None:
            return normal * self.factor
        assert self.to is not None
        noise = default_noise if self.noise is None else self.noise
        return self.to * (1 + rng.gauss(0, noise))


class LogEffect(_TimedEffect):
    """Emits a log message from ``start`` until ``end``, at a rate or a fixed number of times."""

    kind: Literal["log"]
    level: LogLevel
    template: str
    rate_per_min: float | None = Field(default=None, gt=0)
    count: int | None = Field(default=None, gt=0)
    """Emit exactly this many lines, spread over the first minute (or until ``end``)."""
    az: str | None = None
    """Only pods in this availability zone emit the message."""
    fields: dict[str, FieldSpec] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _one_volume(self) -> Self:
        if (self.rate_per_min is None) == (self.count is None):
            raise ValueError(f"{self.service}: set exactly one of 'rate_per_min' or 'count'")
        return self

    def covers(self, ts: datetime) -> bool:
        return self.start <= ts and (self.end is None or ts < self.end)


Effect = Annotated[MetricEffect | LogEffect, Field(discriminator="kind")]


class FaultKind(StrEnum):
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    RATE_LIMITED = "rate_limited"
    PARTIAL = "partial"


_PARTIAL_SCOPES: dict[ToolName, frozenset[str]] = {
    ToolName.QUERY_LOGS: frozenset({"missing_az", "missing_before"}),
    ToolName.QUERY_METRICS: frozenset({"missing_services"}),
    ToolName.GET_CHANGE_HISTORY: frozenset(),
    ToolName.GET_SERVICE_DEPENDENCIES: frozenset(),
    ToolName.SEARCH_INCIDENT_HISTORY: frozenset(),
}


class ToolFault(DomainModel):
    """A failure of one investigation tool's backend during the incident.

    Timeouts, outages and rate limits hit the invocations listed in ``invocations``
    (1-based, counting every attempt including retries), or every invocation when it is
    omitted. A partial fault describes data the backend cannot return at all.
    """

    tool: ToolName
    kind: FaultKind
    invocations: tuple[int, ...] | None = None
    missing_az: str | None = None
    missing_before: AwareDatetime | None = None
    missing_services: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _coherent(self) -> Self:
        scopes = set()
        if self.missing_az is not None:
            scopes.add("missing_az")
        if self.missing_before is not None:
            scopes.add("missing_before")
        if self.missing_services:
            scopes.add("missing_services")
        if self.kind is not FaultKind.PARTIAL:
            if scopes:
                raise ValueError(f"{self.tool}: only partial faults describe missing data")
            return self
        if not scopes:
            raise ValueError(f"{self.tool}: a partial fault must say what is missing")
        if self.invocations is not None:
            raise ValueError(f"{self.tool}: partial faults apply to every invocation")
        if unsupported := scopes - _PARTIAL_SCOPES[self.tool]:
            raise ValueError(f"{self.tool} cannot be missing {', '.join(sorted(unsupported))}")
        return self

    def applies_to(self, invocation: int) -> bool:
        return self.invocations is None or invocation in self.invocations


class Scenario(DomainModel):
    seed: int
    window: TimeWindow
    changes: tuple[ChangeEvent, ...] = ()
    effects: tuple[Effect, ...] = ()
    faults: tuple[ToolFault, ...] = ()

    def metric_effects(self) -> list[MetricEffect]:
        return [effect for effect in self.effects if isinstance(effect, MetricEffect)]

    def log_effects(self) -> list[LogEffect]:
        return [effect for effect in self.effects if isinstance(effect, LogEffect)]

    def check_against(self, topology: Topology) -> None:
        """Raise ``ValueError`` if the scenario refers to anything the topology lacks."""
        names = {node.name for node in topology.nodes}
        for change in self.changes:
            if change.service not in names:
                raise ValueError(f"{change.id}: unknown service {change.service!r}")
            if not self.window.contains(change.ts):
                raise ValueError(f"{change.id}: outside the scenario window")
        for effect in self.effects:
            if effect.service not in names:
                raise ValueError(f"effect on unknown service {effect.service!r}")
            if not self.window.contains(effect.start):
                raise ValueError(f"effect on {effect.service} starts outside the scenario window")
            if effect.end is not None and effect.end <= effect.start:
                raise ValueError(f"effect on {effect.service} ends before it starts")
        for metric_effect in self.metric_effects():
            if metric_effect.metric not in topology.metric_specs(metric_effect.service):
                raise ValueError(f"{metric_effect.service} has no metric {metric_effect.metric!r}")
        for log_effect in self.log_effects():
            if topology.node(log_effect.service).pods == 0:
                raise ValueError(f"{log_effect.service} has no pods to emit logs from")
            if log_effect.az is not None and log_effect.az not in topology.availability_zones:
                raise ValueError(f"effect on {log_effect.service}: unknown zone {log_effect.az!r}")
        for fault in self.faults:
            if fault.missing_az is not None and fault.missing_az not in topology.availability_zones:
                raise ValueError(f"{fault.tool} fault: unknown zone {fault.missing_az!r}")
            if unknown := set(fault.missing_services) - names:
                raise ValueError(f"{fault.tool} fault: unknown services {sorted(unknown)}")
