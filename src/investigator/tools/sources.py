"""The data the tools read, over rendered telemetry.

Logs and metrics are read through protocols so that missing data (a lost log shard, an
expired retention window, a service with no metrics) can be layered on as decorators in
``missing_data.py`` without the tools knowing.
"""

from bisect import bisect_left
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from investigator.domain.base import DomainModel
from investigator.domain.telemetry import (
    ChangeEvent,
    DependencyEdge,
    LogLevel,
    LogRecord,
    MetricSeries,
    TimeWindow,
)
from investigator.world.store import TelemetryStore
from investigator.world.topology import NodeKind, Topology


@dataclass(frozen=True)
class Found[T]:
    """Items a backend returned, plus notices about data it could not return."""

    items: tuple[T, ...]
    notices: tuple[str, ...] = ()


@dataclass(frozen=True)
class LogSearch:
    service: str
    start: datetime
    end: datetime
    min_level: LogLevel = LogLevel.INFO
    contains: str | None = None
    az: str | None = None

    def matches(self, record: LogRecord) -> bool:
        return (
            self.start <= record.ts < self.end
            and record.level.at_least(self.min_level)
            and (self.az is None or record.az == self.az)
            and (self.contains is None or self.contains.lower() in record.message.lower())
        )


class LogSource(Protocol):
    def coverage(self) -> TimeWindow: ...

    def search(self, query: LogSearch) -> Found[LogRecord]: ...


class MetricSource(Protocol):
    def coverage(self) -> TimeWindow: ...

    def catalog(self, service: str) -> tuple[MetricSeries, ...]: ...

    def series(self, service: str, name: str) -> Found[MetricSeries]: ...


class ServiceInfo(DomainModel):
    name: str
    kind: NodeKind
    team: str | None


class StoreLogSource:
    def __init__(self, store: TelemetryStore) -> None:
        self._window = store.window
        self._by_service: dict[str, list[LogRecord]] = defaultdict(list)
        for record in store.logs:
            self._by_service[record.service].append(record)
        self._timestamps = {
            name: [r.ts for r in records] for name, records in self._by_service.items()
        }

    def coverage(self) -> TimeWindow:
        return self._window

    def search(self, query: LogSearch) -> Found[LogRecord]:
        records = self._by_service.get(query.service, [])
        first = bisect_left(self._timestamps.get(query.service, []), query.start)
        matched = []
        for record in records[first:]:
            if record.ts >= query.end:
                break
            if query.matches(record):
                matched.append(record)
        return Found(tuple(matched))


class StoreMetricSource:
    def __init__(self, store: TelemetryStore) -> None:
        self._window = store.window
        self._series = store.metrics

    def coverage(self) -> TimeWindow:
        return self._window

    def catalog(self, service: str) -> tuple[MetricSeries, ...]:
        return tuple(
            sorted((s for s in self._series.values() if s.service == service), key=lambda s: s.name)
        )

    def series(self, service: str, name: str) -> Found[MetricSeries]:
        found = [s for s in self._series.values() if s.service == service and s.name == name]
        return Found(tuple(found))


class StoreChangeSource:
    def __init__(self, store: TelemetryStore) -> None:
        self._changes = store.changes

    def changes(self, start: datetime, end: datetime) -> Found[ChangeEvent]:
        return Found(tuple(c for c in self._changes if start <= c.ts < end))


class ServiceCatalog:
    """What services exist, what kind they are, and what calls what."""

    def __init__(self, topology: Topology) -> None:
        self._topology = topology

    def names(self) -> tuple[str, ...]:
        return tuple(node.name for node in self._topology.nodes)

    def service(self, name: str) -> ServiceInfo:
        node = self._topology.node(name)
        return ServiceInfo(name=node.name, kind=node.kind, team=node.team)

    def zones(self) -> tuple[str, ...]:
        return self._topology.availability_zones

    def edges(self) -> tuple[DependencyEdge, ...]:
        return self._topology.edges
