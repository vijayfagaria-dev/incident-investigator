"""The orchestrator decides where to look: the first plan, and which follow-ups to pursue."""

from collections.abc import Sequence

from investigator.agents import briefing
from investigator.agents.base import Agent, load_prompt
from investigator.agents.outputs import FollowUpPlan, InvestigationPlan, PlannedTask
from investigator.domain.investigation import AgentRole, EvidenceRequest
from investigator.domain.tools import ToolName
from investigator.runtime.agent_loop import AgentLoop, AgentRun, AgentSpec
from investigator.runtime.blackboard import BoardView

PLAN_STEPS = 3
"""Tool steps for planning: enough to look up the dependency graph around the reports."""


class Orchestrator:
    """Decides where the specialists look: the first plan, and which follow-ups to pursue."""

    def __init__(self, loop: AgentLoop) -> None:
        self._planner = Agent(
            loop,
            AgentSpec(
                role=AgentRole.ORCHESTRATOR,
                system_prompt=load_prompt("orchestrator_plan"),
                output_model=InvestigationPlan,
                tools=(ToolName.GET_SERVICE_DEPENDENCIES,),
                max_steps=PLAN_STEPS,
            ),
        )
        self._prioritiser = Agent(
            loop,
            AgentSpec(
                role=AgentRole.ORCHESTRATOR,
                system_prompt=load_prompt(
                    "orchestrator_followup", evidence=load_prompt("evidence")
                ),
                output_model=FollowUpPlan,
            ),
        )

    async def plan(self, view: BoardView) -> AgentRun[InvestigationPlan]:
        return await self._planner.run(briefing.incident(view.incident))

    async def follow_up(
        self,
        view: BoardView,
        requests: Sequence[EvidenceRequest],
        done: Sequence[PlannedTask],
        limit: int,
    ) -> AgentRun[FollowUpPlan]:
        done_lines = "\n".join(
            f"- {t.agent}: {t.focus} ({', '.join(t.services)}, "
            f"{briefing.when(t.start)} to {briefing.when(t.end)})"
            for t in done
        )
        brief = "\n\n".join(
            (
                briefing.incident(view.incident),
                f"Evidence requests:\n{briefing.requests(requests)}",
                f"Current hypotheses:\n{briefing.hypotheses(view.hypotheses)}",
                briefing.review(view.latest_review),
                f"Work already done:\n{done_lines or briefing.NONE}",
                f"Choose at most {limit} tasks.",
            )
        )
        return await self._prioritiser.run(brief)
