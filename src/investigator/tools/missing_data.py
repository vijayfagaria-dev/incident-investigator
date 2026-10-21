"""Backends that cannot return all their data, as a scenario's partial faults describe.

Each wrapper removes what its backend would be missing and says so in a notice, the way a
real log or metrics store reports an unavailable shard or an expired retention window.
"""

from collections.abc import Iterable
from datetime import datetime

from investigator.domain.telemetry import LogRecord, MetricSeries, TimeWindow
from investigator.domain.tools import ToolName
from investigator.tools.sources import Found, LogSearch, LogSource, MetricSource
from investigator.world.scenario import FaultKind, ToolFault


class ZoneOutageLogs:
    def __init__(self, inner: LogSource, zone: str) -> None:
        self._inner = inner
        self._zone = zone

    def coverage(self) -> TimeWindow:
        return self._inner.coverage()

    def search(self, query: LogSearch) -> Found[LogRecord]:
        found = self._inner.search(query)
        notice = f"log shard for {self._zone} is unavailable; results exclude pods in {self._zone}"
        return Found(tuple(r for r in found.items if r.az != self._zone), (*found.notices, notice))


class ExpiredLogs:
    def __init__(self, inner: LogSource, cutoff: datetime) -> None:
        self._inner = inner
        self._cutoff = cutoff

    def coverage(self) -> TimeWindow:
        return self._inner.coverage()

    def search(self, query: LogSearch) -> Found[LogRecord]:
        found = self._inner.search(query)
        if query.start >= self._cutoff:
            return found
        notice = f"logs before {self._cutoff:%Y-%m-%d %H:%M} UTC have expired and are not returned"
        kept = tuple(r for r in found.items if r.ts >= self._cutoff)
        return Found(kept, (*found.notices, notice))


class MissingServiceMetrics:
    """No metrics at all for some services."""

    def __init__(self, inner: MetricSource, services: Iterable[str]) -> None:
        self._inner = inner
        self._services = frozenset(services)

    def coverage(self) -> TimeWindow:
        return self._inner.coverage()

    def catalog(self, service: str) -> tuple[MetricSeries, ...]:
        return self._inner.catalog(service)

    def series(self, service: str, name: str) -> Found[MetricSeries]:
        found = self._inner.series(service, name)
        if service not in self._services:
            return found
        return Found(
            (), (*found.notices, f"metrics for {service} are unavailable from the backend")
        )


def with_missing_logs(source: LogSource, faults: Iterable[ToolFault]) -> LogSource:
    for fault in _partial_faults(faults, ToolName.QUERY_LOGS):
        if fault.missing_az is not None:
            source = ZoneOutageLogs(source, fault.missing_az)
        if fault.missing_before is not None:
            source = ExpiredLogs(source, fault.missing_before)
    return source


def with_missing_metrics(source: MetricSource, faults: Iterable[ToolFault]) -> MetricSource:
    for fault in _partial_faults(faults, ToolName.QUERY_METRICS):
        source = MissingServiceMetrics(source, fault.missing_services)
    return source


def _partial_faults(faults: Iterable[ToolFault], tool: ToolName) -> list[ToolFault]:
    return [f for f in faults if f.tool is tool and f.kind is FaultKind.PARTIAL]
