"""Argument checks shared by tools; each raises ``InvalidQuery`` saying how to fix the call."""

from collections.abc import Iterable
from datetime import datetime

from investigator.domain.telemetry import TimeWindow
from investigator.tools.results import InvalidQuery
from investigator.tools.sources import ServiceCatalog


def require_services(catalog: ServiceCatalog, names: Iterable[str]) -> None:
    unknown = sorted(set(names) - set(catalog.names()))
    if unknown:
        raise InvalidQuery(
            f"unknown service {', '.join(unknown)}; known services: {', '.join(catalog.names())}"
        )


def require_range(start: datetime, end: datetime) -> None:
    if end <= start:
        raise InvalidQuery("end must be after start")


def coverage_warnings(coverage: TimeWindow, start: datetime, end: datetime) -> tuple[str, ...]:
    """Explain an empty or short answer caused by asking outside the recorded window."""
    if start >= coverage.start and end <= coverage.end:
        return ()
    return (
        f"telemetry is only recorded from {coverage.start:%Y-%m-%d %H:%M} "
        f"to {coverage.end:%H:%M} UTC; the rest of the requested range is empty",
    )
