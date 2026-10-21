"""The reporting agent writes the narrative; the outcome itself is decided by policy beforehand."""

from collections.abc import Sequence

from investigator.agents import briefing
from investigator.agents.base import Agent, load_prompt
from investigator.agents.outputs import ReportNarrative
from investigator.domain.causes import Outcome
from investigator.domain.investigation import AgentRole, Hypothesis
from investigator.runtime.agent_loop import AgentLoop, AgentSpec
from investigator.runtime.blackboard import BoardView


class ReportingAgent(Agent[ReportNarrative]):
    def __init__(self, loop: AgentLoop) -> None:
        super().__init__(
            loop,
            AgentSpec(
                role=AgentRole.REPORTING,
                system_prompt=load_prompt("reporting"),
                output_model=ReportNarrative,
            ),
        )

    def brief(
        self,
        view: BoardView,
        outcome: Outcome,
        reasons: Sequence[str],
        ranked: Sequence[Hypothesis],
        termination: str,
    ) -> str:
        decided = f"Outcome (decided by policy): {outcome}"
        if reasons:
            decided += f", because {'; '.join(reasons)}"
        return "\n\n".join(
            (
                briefing.incident(view.incident),
                decided,
                f"Investigation stopped because: {termination}",
                f"Ranked hypotheses:\n{briefing.hypotheses(ranked)}",
                briefing.review(view.latest_review),
                f"Observations:\n{briefing.observations(view.observations)}",
                f"Evidence gaps:\n{briefing.gaps(view.gaps)}",
            )
        )
