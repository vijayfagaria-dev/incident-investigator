"""Before anyone forms a theory, list every change in the window.

An agent asked to look at some services can filter the rest out and miss the change that
matters. Listing all changes once, with no filter, guarantees nothing that changed is
overlooked; deciding which change matters is still the agents' job.
"""

from datetime import datetime, timedelta

from investigator.agents.base import gaps_from
from investigator.domain.investigation import AgentRole, ObservationDraft
from investigator.domain.telemetry import ChangeEvent
from investigator.domain.tools import ToolName, ToolStatus
from investigator.runtime.blackboard import Blackboard
from investigator.tools.changes import ChangeQueryResult
from investigator.tools.executor import ToolExecutor

CENSUS_SOURCE = "change-census"
LOOKBACK = timedelta(minutes=60)


async def take_change_census(
    executor: ToolExecutor, board: Blackboard, start: datetime, end: datetime
) -> None:
    reported = board.incident.reported_at
    start, end = min(start, reported - LOOKBACK), max(end, reported)
    result = await executor.execute(
        ToolName.GET_CHANGE_HISTORY,
        {"start": start.isoformat(), "end": end.isoformat()},
        caller=AgentRole.ORCHESTRATOR,
    )
    board.record_tool_results([result])
    changes = (
        ChangeQueryResult.model_validate(result.output).changes
        if result.status is not ToolStatus.ERROR and result.output is not None
        else ()
    )
    board.add_findings(
        CENSUS_SOURCE,
        observations=[
            ObservationDraft(statement=_describe(c), artifacts=(c.id,), service=c.service)
            for c in changes
        ],
        gaps=gaps_from([result]),
    )


def _describe(change: ChangeEvent) -> str:
    details = ", ".join(f"{key}: {value}" for key, value in change.details.items())
    return (
        f"{change.kind} on {change.service} at {change.ts:%H:%M:%S} UTC by {change.actor}: "
        f"{change.summary}{f' ({details})' if details else ''}"
    )
