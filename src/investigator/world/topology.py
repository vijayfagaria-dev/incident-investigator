"""The platform every incident runs on: services, datastores, their metrics and their calls."""

from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from investigator.domain.base import DomainModel
from investigator.domain.telemetry import DependencyEdge, LogLevel


class NodeKind(StrEnum):
    SERVICE = "service"
    DATASTORE = "datastore"
    QUEUE = "queue"
    EXTERNAL = "external"
    """Third-party systems we call but cannot observe."""


class MetricSpec(DomainModel):
    unit: str
    baseline: float
    noise: float = Field(default=0.05, ge=0)
    """Relative standard deviation of each sample around the baseline."""
    follows_traffic: bool = False
    floor: float = 0.0
    ceiling: float | None = None


class UniformField(DomainModel):
    """A log field drawn uniformly between two bounds; whole-number bounds give integers."""

    uniform: tuple[float, float]


class ChoiceField(DomainModel):
    choice: tuple[str | int | float, ...]


FieldSpec = UniformField | ChoiceField | str | int | float
"""How a log template field gets its value: drawn at random, or a constant."""


class BackgroundLog(DomainModel):
    """A message the node emits in normal operation, healthy or not."""

    level: LogLevel
    template: str
    rate_per_hour: float = Field(gt=0)
    fields: dict[str, FieldSpec] = Field(default_factory=dict)


class Node(DomainModel):
    name: str
    kind: NodeKind
    team: str | None = None
    pods: int = Field(default=0, ge=0)
    profile: str | None = None
    metrics: dict[str, MetricSpec] = Field(default_factory=dict)
    """Metrics specific to this node; they replace profile metrics of the same name."""
    routes: tuple[str, ...] = ()
    """HTTP routes, as ``METHOD /path``; nodes with routes emit sampled access logs."""
    access_logs_per_pod_minute: float = Field(default=6, ge=0)
    background_logs: tuple[BackgroundLog, ...] = ()


class Traffic(DomainModel):
    diurnal_amplitude: float = Field(ge=0, lt=1)
    peak_hour_utc: float = Field(ge=0, lt=24)


class Topology(DomainModel):
    availability_zones: tuple[str, ...] = Field(min_length=1)
    traffic: Traffic
    metric_profiles: dict[str, dict[str, MetricSpec]]
    nodes: tuple[Node, ...]
    edges: tuple[DependencyEdge, ...]

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        names = [node.name for node in self.nodes]
        if len(names) != len(set(names)):
            raise ValueError("node names must be unique")
        known = set(names)
        for edge in self.edges:
            if edge.source not in known or edge.target not in known:
                raise ValueError(f"edge {edge.id} references an unknown node")
        for node in self.nodes:
            if node.profile is not None and node.profile not in self.metric_profiles:
                raise ValueError(f"{node.name}: unknown metric profile {node.profile!r}")
            if node.kind is NodeKind.EXTERNAL and (node.pods or node.profile or node.metrics):
                raise ValueError(f"{node.name}: external nodes have no pods or metrics")
            if (node.routes or node.background_logs) and node.pods == 0:
                raise ValueError(f"{node.name}: logs need at least one pod to come from")
            if node.routes and not {"error_rate", "latency_p50_ms", "latency_p99_ms"} <= set(
                self.metric_specs(node.name)
            ):
                raise ValueError(f"{node.name}: nodes with routes need error and latency metrics")
        return self

    def node(self, name: str) -> Node:
        for node in self.nodes:
            if node.name == name:
                return node
        raise KeyError(name)

    def metric_specs(self, name: str) -> dict[str, MetricSpec]:
        node = self.node(name)
        profile = self.metric_profiles[node.profile] if node.profile else {}
        return {**profile, **node.metrics}
