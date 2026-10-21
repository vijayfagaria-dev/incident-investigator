"""The reasoning agent proposes and ranks root-cause hypotheses from the board's evidence."""

from investigator.agents import briefing
from investigator.agents.base import Agent, commit_with_keys, load_prompt
from investigator.agents.outputs import HypothesisSet
from investigator.domain.causes import CauseCategory
from investigator.domain.investigation import AgentRole
from investigator.domain.tools import ToolName
from investigator.runtime.agent_loop import AgentLoop, AgentRun, AgentSpec
from investigator.runtime.blackboard import Blackboard, BoardView, Commit


class ReasoningAgent(Agent[HypothesisSet]):
    def __init__(self, loop: AgentLoop, max_steps: int) -> None:
        super().__init__(
            loop,
            AgentSpec(
                role=AgentRole.REASONING,
                system_prompt=load_prompt(
                    "reasoning",
                    categories=", ".join(category.value for category in CauseCategory),
                    evidence=load_prompt("evidence"),
                ),
                output_model=HypothesisSet,
                tools=(ToolName.SEARCH_INCIDENT_HISTORY,),
                max_steps=max_steps,
            ),
        )

    def brief(self, view: BoardView) -> str:
        latest = view.latest_review
        return "\n\n".join(
            (
                briefing.incident(view.incident),
                f"Round {view.round}.",
                f"Observations:\n{briefing.observations(view.observations)}",
                f"Evidence gaps:\n{briefing.gaps(view.gaps)}",
                f"Leads raised by specialists (not all followed up):\n{briefing.leads(view.leads)}",
                f"Hypotheses so far:\n{briefing.hypotheses(view.hypotheses)}",
                briefing.review(latest),
            )
        )

    def commit(self, board: Blackboard, run: AgentRun[HypothesisSet], source: str) -> Commit:
        """Commit analogies and assumptions, then hypotheses with their local keys resolved."""
        board.record_tool_results(run.tool_results)
        output = run.output
        commit = commit_with_keys(
            board,
            source,
            observations=output.analogies,
            assumptions=output.assumptions,
            hypotheses=output.hypotheses,
        )
        board.add_requests(output.requests, requested_by=AgentRole.REASONING)
        return commit
