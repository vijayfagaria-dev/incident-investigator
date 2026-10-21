from pydantic import AwareDatetime, Field

from investigator.domain.telemetry import ChangeEvent, ChangeKind
from investigator.domain.tools import ToolName
from investigator.tools.base import ToolArgs, ToolOutput
from investigator.tools.sources import ServiceCatalog, StoreChangeSource
from investigator.tools.validation import require_range, require_services

MAX_CHANGES = 50


class ChangeQuery(ToolArgs):
    start: AwareDatetime = Field(description="Start of the range (inclusive), ISO 8601 UTC.")
    end: AwareDatetime = Field(description="End of the range (exclusive), ISO 8601 UTC.")
    services: tuple[str, ...] = Field(default=(), description="Only these services; all if empty.")
    kinds: tuple[ChangeKind, ...] = Field(default=(), description="Only these kinds; all if empty.")


class ChangeQueryResult(ToolOutput):
    changes: tuple[ChangeEvent, ...]

    def artifacts(self) -> tuple[str, ...]:
        return tuple(change.id for change in self.changes)


class ChangeHistoryTool:
    name = ToolName.GET_CHANGE_HISTORY
    description = (
        "List production changes in a time range: deploys, config changes, feature-flag "
        "changes, secret rotations and infrastructure work, oldest first, each with who made "
        "it and what changed. Change ids can be cited."
    )
    args_model = ChangeQuery

    def __init__(self, changes: StoreChangeSource, catalog: ServiceCatalog) -> None:
        self._changes = changes
        self._catalog = catalog

    async def run(self, args: ChangeQuery) -> ChangeQueryResult:
        require_range(args.start, args.end)
        require_services(self._catalog, args.services)
        found = self._changes.changes(args.start, args.end)
        selected = [
            change
            for change in sorted(found.items, key=lambda change: change.ts)
            if (not args.services or change.service in args.services)
            and (not args.kinds or change.kind in args.kinds)
        ]
        warnings: tuple[str, ...] = ()
        if len(selected) > MAX_CHANGES:
            warnings = (f"{len(selected) - MAX_CHANGES} later changes not shown; narrow the range",)
        return ChangeQueryResult(
            changes=tuple(selected[:MAX_CHANGES]), notices=found.notices, warnings=warnings
        )
