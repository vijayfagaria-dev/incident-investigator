"""The observability and dependency specialists: they gather facts, never conclusions."""

from investigator.agents import briefing
from investigator.agents.base import Agent, gaps_from, load_prompt
from investigator.agents.outputs import Findings, PlannedTask
from investigator.domain.investigation import AgentRole, EvidenceRequest
from investigator.domain.tools import ToolName
from investigator.runtime.agent_loop import AgentLoop, AgentRun, AgentSpec
from investigator.runtime.blackboard import Blackboard, BoardView, Commit

TOOLS = {
    AgentRole.OBSERVABILITY: (ToolName.QUERY_LOGS, ToolName.QUERY_METRICS),
    AgentRole.DEPENDENCY: (ToolName.GET_CHANGE_HISTORY, ToolName.GET_SERVICE_DEPENDENCIES),
}


class Specialist(Agent[Findings]):
    """The observability or dependency specialist: a shared brief and commit, its own tools."""

    def __init__(self, loop: AgentLoop, role: AgentRole, max_steps: int) -> None:
        super().__init__(
            loop,
            AgentSpec(
                role=role,
                system_prompt=load_prompt(role),
                output_model=Findings,
                tools=TOOLS[role],
                max_steps=max_steps,
            ),
        )

    def brief(
        self, view: BoardView, task: PlannedTask, request: EvidenceRequest | None = None
    ) -> str:
        sections = [
            briefing.incident(view.incident),
            f"Your assignment: {task.focus}\n"
            f"Services: {', '.join(task.services)}\n"
            f"Time range: {briefing.when(task.start)} to {briefing.when(task.end)}",
        ]
        if request is not None:
            sections.append(f"This answers {request.id}, raised in review: {request.question}")
        if view.observations:
            sections.append(
                "Already established (do not re-report these):\n"
                + briefing.observations(view.observations)
            )
        return "\n\n".join(sections)

    def commit(self, board: Blackboard, run: AgentRun[Findings], source: str) -> Commit:
        board.record_tool_results(run.tool_results)
        return board.add_findings(
            source,
            observations=run.output.observations,
            leads=run.output.leads,
            gaps=[*run.output.gaps, *gaps_from(run.tool_results)],
        )
