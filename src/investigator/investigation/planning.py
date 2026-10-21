"""What the specialists look at when no model decides: a fallback plan, and follow-up tasks."""

from collections.abc import Iterable, Sequence
from datetime import datetime

from investigator.agents.outputs import InvestigationPlan, PlannedTask, Specialty
from investigator.domain.investigation import AgentRole, EvidenceDomain, EvidenceRequest, Lead
from investigator.domain.tools import ToolName, ToolStatus
from investigator.investigation.census import LOOKBACK
from investigator.runtime.blackboard import Blackboard
from investigator.tools.executor import ToolExecutor


async def fallback_plan(executor: ToolExecutor, board: Blackboard) -> InvestigationPlan:
    """Watch the reported services and their neighbours over the hour before the report."""
    incident = board.incident
    services = set(incident.reported_services)
    for service in incident.reported_services:
        result = await executor.execute(
            ToolName.GET_SERVICE_DEPENDENCIES, {"service": service, "direction": "both"}
        )
        board.record_tool_results([result])
        if result.status is not ToolStatus.ERROR and result.output is not None:
            services |= {info["name"] for info in result.output["services"]}
    if not services:
        raise ValueError("the incident names no services, so there is nowhere to start")

    start, end = incident.reported_at - LOOKBACK, incident.reported_at
    reported = tuple(sorted(incident.reported_services)) or tuple(sorted(services))
    return InvestigationPlan(
        rationale="fallback plan: the orchestrator did not produce one",
        tasks=(
            PlannedTask(
                agent=AgentRole.OBSERVABILITY,
                focus="Establish what is failing on the reported services, and when it started.",
                services=reported,
                start=start,
                end=end,
            ),
            PlannedTask(
                agent=AgentRole.DEPENDENCY,
                focus="List every change on these services and how they depend on each other.",
                services=tuple(sorted(services)),
                start=start,
                end=end,
            ),
        ),
    )


class FollowUpPlanner:
    """Builds follow-up tasks inside the investigation's scope, skipping work already done."""

    def __init__(self, services: Sequence[str], start: datetime, end: datetime) -> None:
        self._services = tuple(services)
        self._start = start
        self._end = end

    def from_leads(
        self, leads: Iterable[Lead], done: Sequence[PlannedTask], limit: int
    ) -> list[PlannedTask]:
        """Leads become tasks only where no specialist has examined those services and times."""
        # Look past the limit, since some candidates turn out to repeat earlier work.
        candidates = self._tasks(leads, done, limit=len(done) + limit)
        return [task for task in candidates if not _covered(task, done)][:limit]

    def from_requests(
        self, requests: Iterable[EvidenceRequest], done: Sequence[PlannedTask], limit: int
    ) -> list[PlannedTask]:
        return self._tasks(requests, done, limit)

    def _tasks(
        self, asks: Iterable[Lead | EvidenceRequest], done: Sequence[PlannedTask], limit: int
    ) -> list[PlannedTask]:
        seen = {_signature(task) for task in done}
        chosen: list[PlannedTask] = []
        for ask in asks:
            agent = _specialty(ask.domain)
            if agent is None or len(chosen) >= limit:
                continue
            task = PlannedTask(
                agent=agent,
                focus=ask.question,
                services=(ask.service,) if ask.service else self._services,
                start=ask.start or self._start,
                end=ask.end or self._end,
            )
            if _signature(task) not in seen:
                seen.add(_signature(task))
                chosen.append(task)
        return chosen


def _specialty(domain: EvidenceDomain) -> Specialty | None:
    if domain is EvidenceDomain.OBSERVABILITY:
        return AgentRole.OBSERVABILITY
    if domain is EvidenceDomain.CHANGES:
        return AgentRole.DEPENDENCY
    return None


def _signature(task: PlannedTask) -> tuple[str, frozenset[str], str]:
    return task.agent, frozenset(task.services), task.focus.strip().lower()


def _covered(task: PlannedTask, done: Sequence[PlannedTask]) -> bool:
    return any(
        earlier.agent == task.agent
        and set(task.services) <= set(earlier.services)
        and earlier.start <= task.start
        and task.end <= earlier.end
        for earlier in done
    )
