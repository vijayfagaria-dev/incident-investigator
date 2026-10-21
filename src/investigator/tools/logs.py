import re
from collections import defaultdict
from typing import Literal

from pydantic import AwareDatetime, Field

from investigator.domain.base import DomainModel
from investigator.domain.telemetry import LogLevel, LogRecord
from investigator.domain.tools import ToolName
from investigator.tools.base import ToolArgs, ToolOutput
from investigator.tools.results import InvalidQuery
from investigator.tools.sources import LogSearch, LogSource, ServiceCatalog
from investigator.tools.validation import coverage_warnings, require_range, require_services

_PLACEHOLDER = re.compile(r"\{(\w+)\}")
_CURSOR = re.compile(r"^offset:(\d+)$")


class LogQuery(ToolArgs):
    service: str = Field(description="Service whose logs to search, e.g. payments-service.")
    start: AwareDatetime = Field(description="Start of the range (inclusive), ISO 8601 UTC.")
    end: AwareDatetime = Field(description="End of the range (exclusive), ISO 8601 UTC.")
    min_level: LogLevel = Field(
        default=LogLevel.INFO, description="Only lines at this level or more severe."
    )
    contains: str | None = Field(default=None, description="Case-insensitive text to match.")
    az: str | None = Field(default=None, description="Only lines from pods in this zone.")
    mode: Literal["patterns", "records"] = Field(
        default="patterns",
        description="'patterns' groups similar lines with counts; 'records' returns lines.",
    )
    limit: int = Field(default=10, ge=1, le=100, description="Maximum patterns or lines.")
    cursor: str | None = Field(
        default=None, description="next_cursor from a previous 'records' query, to page on."
    )


class LogPattern(DomainModel):
    pattern: str
    level: LogLevel
    count: int
    first_seen: AwareDatetime
    last_seen: AwareDatetime
    example_id: str
    example: str


class LogEntry(DomainModel):
    id: str
    ts: AwareDatetime
    pod: str
    az: str
    level: LogLevel
    message: str
    trace_id: str | None


class LogQueryResult(ToolOutput):
    service: str
    matched: int
    patterns: tuple[LogPattern, ...] = ()
    records: tuple[LogEntry, ...] = ()
    next_cursor: str | None = None

    def artifacts(self) -> tuple[str, ...]:
        return tuple(p.example_id for p in self.patterns) + tuple(r.id for r in self.records)


class QueryLogsTool:
    name = ToolName.QUERY_LOGS
    description = (
        "Search one service's logs in a time range. The default 'patterns' mode groups similar "
        "lines and gives counts with first and last occurrence: the best first look. Use "
        "mode='records' with 'contains' to read individual lines. Pattern examples and lines "
        "carry ids you can cite as evidence."
    )
    args_model = LogQuery

    def __init__(self, logs: LogSource, catalog: ServiceCatalog) -> None:
        self._logs = logs
        self._catalog = catalog

    async def run(self, args: LogQuery) -> LogQueryResult:
        require_services(self._catalog, [args.service])
        require_range(args.start, args.end)
        if args.az is not None and args.az not in self._catalog.zones():
            raise InvalidQuery(f"unknown zone {args.az}; zones: {', '.join(self._catalog.zones())}")
        if args.cursor is not None and args.mode == "patterns":
            raise InvalidQuery("cursor only applies to mode='records'")

        found = self._logs.search(
            LogSearch(args.service, args.start, args.end, args.min_level, args.contains, args.az)
        )
        warnings = coverage_warnings(self._logs.coverage(), args.start, args.end)
        if args.mode == "patterns":
            return self._patterns(args, found.items, found.notices, warnings)
        return self._records(args, found.items, found.notices, warnings)

    @staticmethod
    def _patterns(
        args: LogQuery,
        records: tuple[LogRecord, ...],
        notices: tuple[str, ...],
        warnings: tuple[str, ...],
    ) -> LogQueryResult:
        groups: dict[tuple[str, LogLevel], list[LogRecord]] = defaultdict(list)
        for record in records:
            groups[(record.template, record.level)].append(record)
        ranked = sorted(groups.items(), key=lambda item: (-len(item[1]), item[0][0]))
        if len(ranked) > args.limit:
            warnings = (*warnings, f"{len(ranked) - args.limit} less frequent patterns not shown")
        patterns = tuple(
            LogPattern(
                pattern=_PLACEHOLDER.sub(r"<\1>", template),
                level=level,
                count=len(group),
                first_seen=group[0].ts,
                last_seen=group[-1].ts,
                example_id=group[0].id,
                example=group[0].message,
            )
            for (template, level), group in ranked[: args.limit]
        )
        return LogQueryResult(
            service=args.service,
            matched=len(records),
            patterns=patterns,
            notices=notices,
            warnings=warnings,
        )

    @staticmethod
    def _records(
        args: LogQuery,
        records: tuple[LogRecord, ...],
        notices: tuple[str, ...],
        warnings: tuple[str, ...],
    ) -> LogQueryResult:
        offset = 0
        if args.cursor is not None:
            match = _CURSOR.match(args.cursor)
            if match is None:
                raise InvalidQuery(f"malformed cursor {args.cursor!r}")
            offset = int(match.group(1))
        page = records[offset : offset + args.limit]
        more = offset + len(page) < len(records)
        return LogQueryResult(
            service=args.service,
            matched=len(records),
            records=tuple(
                LogEntry(
                    id=r.id,
                    ts=r.ts,
                    pod=r.pod,
                    az=r.az,
                    level=r.level,
                    message=r.message,
                    trace_id=r.trace_id,
                )
                for r in page
            ),
            next_cursor=f"offset:{offset + len(page)}" if more else None,
            notices=notices,
            warnings=warnings,
        )
