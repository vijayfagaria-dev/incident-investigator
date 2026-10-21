import math
from collections.abc import Sequence
from datetime import timedelta
from statistics import fmean
from typing import Self

from pydantic import AwareDatetime, Field, model_validator

from investigator.domain.base import DomainModel
from investigator.domain.telemetry import MetricSeries
from investigator.domain.tools import ToolName
from investigator.tools.base import ToolArgs, ToolOutput
from investigator.tools.results import InvalidQuery
from investigator.tools.sources import MetricSource, ServiceCatalog
from investigator.tools.validation import coverage_warnings, require_range, require_services

MAX_POINTS = 30
BASELINE = timedelta(hours=1)


class MetricQuery(ToolArgs):
    service: str = Field(description="Service whose metrics to read.")
    metric: str | None = Field(
        default=None,
        description=(
            "Metric to fetch. Omit it to summarise every metric the service reports over the "
            "range, or, without a range, to list them."
        ),
    )
    start: AwareDatetime | None = Field(
        default=None, description="Start of the range (inclusive), ISO 8601 UTC."
    )
    end: AwareDatetime | None = Field(
        default=None, description="End of the range (exclusive), ISO 8601 UTC."
    )
    step_minutes: int = Field(default=1, ge=1, le=60, description="Resolution of the points.")

    @model_validator(mode="after")
    def _range_with_metric(self) -> Self:
        if self.metric is not None and (self.start is None or self.end is None):
            raise ValueError("start and end are required when fetching a metric")
        return self


class MetricSummary(DomainModel):
    min: float
    max: float
    mean: float
    first: float
    last: float
    baseline_mean: float | None
    """Mean over the hour before ``start``, for comparison; absent when not recorded."""


class MetricInfo(DomainModel):
    id: str
    name: str
    unit: str
    summary: MetricSummary | None = None
    """Present when the query gave a range: the metric over it, against its baseline."""


class MetricQueryResult(ToolOutput):
    service: str
    available: tuple[MetricInfo, ...] = ()
    series_id: str | None = None
    unit: str | None = None
    step_minutes: int | None = None
    points: tuple[tuple[AwareDatetime, float], ...] = ()
    summary: MetricSummary | None = None

    def artifacts(self) -> tuple[str, ...]:
        if self.series_id and self.points:
            return (self.series_id,)
        return tuple(info.id for info in self.available if info.summary is not None)


class QueryMetricsTool:
    name = ToolName.QUERY_METRICS
    description = (
        "Read one metric for one service over a time range, with a summary that compares the "
        "range against the hour before it. Omit 'metric' to summarise every metric the "
        "service reports over the range in one call, like a dashboard; omit the range too to "
        f"just list them. Ranges are downsampled to at most {MAX_POINTS} points. Series ids "
        "can be cited."
    )
    args_model = MetricQuery

    def __init__(self, metrics: MetricSource, catalog: ServiceCatalog) -> None:
        self._metrics = metrics
        self._catalog = catalog

    async def run(self, args: MetricQuery) -> MetricQueryResult:
        require_services(self._catalog, [args.service])
        reported = self._metrics.catalog(args.service)
        start, end = args.start, args.end
        if args.metric is None and (start is None or end is None):
            return MetricQueryResult(
                service=args.service,
                available=tuple(MetricInfo(id=s.id, name=s.name, unit=s.unit) for s in reported),
            )
        # The argument model rejects a named metric without a range.
        assert start is not None
        assert end is not None
        require_range(start, end)
        if args.metric is None:
            return self._overview(args.service, reported, start, end)

        found = self._metrics.series(args.service, args.metric)
        if not found.items and not found.notices:
            names = ", ".join(s.name for s in reported) or "none"
            raise InvalidQuery(f"{args.service} has no metric {args.metric}; available: {names}")
        warnings = coverage_warnings(self._metrics.coverage(), start, end)
        if not found.items:
            return MetricQueryResult(service=args.service, notices=found.notices, warnings=warnings)

        series = found.items[0]
        samples = _samples(series, start, end)
        step = max(args.step_minutes, math.ceil(len(samples) / MAX_POINTS))
        if step > args.step_minutes:
            warnings = (
                *warnings,
                f"step raised to {step} minutes to stay within {MAX_POINTS} points",
            )
        values = [v for _, v in samples]
        return MetricQueryResult(
            service=args.service,
            series_id=series.id,
            unit=series.unit,
            step_minutes=step,
            points=_downsample(samples, step),
            summary=_summary(values, series, start) if values else None,
            notices=found.notices,
            warnings=warnings,
        )

    def _overview(
        self,
        service: str,
        reported: Sequence[MetricSeries],
        start: AwareDatetime,
        end: AwareDatetime,
    ) -> MetricQueryResult:
        """Every metric's summary over the range, without the points."""
        infos: list[MetricInfo] = []
        notices: list[str] = []
        for entry in reported:
            found = self._metrics.series(service, entry.name)
            for notice in found.notices:
                if notice not in notices:
                    notices.append(notice)
            summary = None
            if found.items:
                values = [v for _, v in _samples(found.items[0], start, end)]
                if values:
                    summary = _summary(values, found.items[0], start)
            infos.append(MetricInfo(id=entry.id, name=entry.name, unit=entry.unit, summary=summary))
        return MetricQueryResult(
            service=service,
            available=tuple(infos),
            notices=tuple(notices),
            warnings=coverage_warnings(self._metrics.coverage(), start, end),
        )


def _samples(
    series: MetricSeries, start: AwareDatetime, end: AwareDatetime
) -> list[tuple[AwareDatetime, float]]:
    return [
        (ts, v)
        for ts, v in zip(series.timestamps(), series.values, strict=True)
        if start <= ts < end
    ]


def _downsample(
    samples: list[tuple[AwareDatetime, float]], step: int
) -> tuple[tuple[AwareDatetime, float], ...]:
    buckets = (samples[i : i + step] for i in range(0, len(samples), step))
    return tuple((bucket[0][0], _round(fmean(v for _, v in bucket))) for bucket in buckets)


def _summary(values: list[float], series: MetricSeries, start: AwareDatetime) -> MetricSummary:
    before = [
        v
        for ts, v in zip(series.timestamps(), series.values, strict=True)
        if start - BASELINE <= ts < start
    ]
    return MetricSummary(
        min=_round(min(values)),
        max=_round(max(values)),
        mean=_round(fmean(values)),
        first=values[0],
        last=values[-1],
        baseline_mean=_round(fmean(before)) if before else None,
    )


def _round(value: float) -> float:
    return float(f"{value:.4g}")
