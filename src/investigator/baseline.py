"""The single-agent baseline: one agent with every tool, answering in one go.

Everything except the architecture is shared with the agent team: the gateway and model,
the tools and their failures, the budget, the board's citation checks, the outcome rule
and the report. Comparing the two therefore measures what the team adds.
"""

from dataclasses import dataclass

from investigator.agents import briefing
from investigator.agents.base import Agent, commit_with_keys, gaps_from, load_prompt
from investigator.agents.outputs import ReportNarrative, SoloAnswer
from investigator.domain.causes import CauseCategory
from investigator.domain.incident import IncidentReport
from investigator.domain.investigation import AgentRole, GapDraft
from investigator.domain.report import Report
from investigator.domain.runs import TaskState
from investigator.domain.tools import ToolName
from investigator.investigation.assembly import assemble, fallback_narrative
from investigator.investigation.config import InvestigationConfig
from investigator.investigation.policy import OutcomeDecision, decide_outcome, standings
from investigator.investigation.run import commit_traced
from investigator.llm.gateway import ModelGateway
from investigator.runtime.agent_loop import AgentLoop, AgentRun, AgentSpec
from investigator.runtime.blackboard import Blackboard, BoardView, Commit
from investigator.runtime.budget import Budget
from investigator.runtime.tasks import TaskResult, run_task
from investigator.tools.executor import ToolExecutor
from investigator.tools.registry import ToolRegistry
from investigator.tracing import RoundEnded, Tracer

TASK_ID = "investigate"


class BaselineAgent(Agent[SoloAnswer]):
    def __init__(self, loop: AgentLoop, max_steps: int) -> None:
        super().__init__(
            loop,
            AgentSpec(
                role=AgentRole.SOLO,
                system_prompt=load_prompt(
                    "solo",
                    categories=", ".join(category.value for category in CauseCategory),
                    evidence=load_prompt("evidence"),
                ),
                output_model=SoloAnswer,
                tools=tuple(ToolName),
                max_steps=max_steps,
            ),
        )

    def brief(self, view: BoardView) -> str:
        return f"{briefing.incident(view.incident)}\n\nInvestigate it and report what you find."

    def commit(self, board: Blackboard, run: AgentRun[SoloAnswer], source: str) -> Commit:
        board.record_tool_results(run.tool_results)
        output = run.output
        gaps = board.add_findings(source, gaps=[*output.gaps, *gaps_from(run.tool_results)])
        commit = commit_with_keys(
            board,
            source,
            observations=output.observations,
            assumptions=output.assumptions,
            hypotheses=output.hypotheses,
        )
        return Commit((*gaps.accepted, *commit.accepted), (*gaps.problems, *commit.problems))


@dataclass(frozen=True)
class SingleAgentInvestigator:
    """The baseline. Each investigation gets a fresh board, budget and tool cache."""

    gateway: ModelGateway
    tools: ToolRegistry
    config: InvestigationConfig
    tracer: Tracer

    async def investigate(self, incident: IncidentReport) -> Report:
        config = self.config
        budget = Budget(config.budget)
        executor = ToolExecutor(self.tools, tracer=self.tracer)
        agent = BaselineAgent(AgentLoop(self.gateway, executor, budget), config.solo_steps)
        board = Blackboard(incident)
        board.start_round()
        result = await run_task(
            TASK_ID,
            agent.role,
            lambda: agent.run(agent.brief(board.view())),
            tracer=self.tracer,
            timeout_s=config.task_timeout_s,
            max_attempts=config.task_attempts,
        )
        answer = self._commit(board, agent, result)
        if answer is not None:
            termination = "the agent finished its investigation"
        else:
            termination = f"the agent failed: {result.error or result.state}"
        decision = decide_outcome(board.view(), config.min_confidence, config.min_margin)
        self.tracer.record(
            RoundEnded(round=1, standings=standings(board.view()), stop_reason=termination)
        )
        narrative = _narrative(answer, decision, termination)
        return assemble(board.view(), decision, narrative, termination, budget.stats(rounds=1))

    def _commit(
        self, board: Blackboard, agent: BaselineAgent, result: TaskResult
    ) -> SoloAnswer | None:
        """Put the answer on the board; a failed run or a faulty answer becomes a gap."""
        if result.state is not TaskState.SUCCEEDED:
            reason = result.error or result.state
            board.add_findings(TASK_ID, gaps=[GapDraft(tool="agent", scope=TASK_ID, reason=reason)])
            return None
        run: AgentRun[SoloAnswer] = result.value
        output = run.output.model_dump(mode="json")
        commit = commit_traced(
            board,
            self.tracer,
            TASK_ID,
            agent.role,
            output,
            lambda: agent.commit(board, run, TASK_ID),
            gap=("agent", TASK_ID),
        )
        return run.output if commit is not None else None


def _narrative(
    answer: SoloAnswer | None, decision: OutcomeDecision, termination: str
) -> ReportNarrative:
    if answer is None:
        return fallback_narrative(decision, termination)
    # Its actions name hypotheses by labels the board never assigned, so unlink them.
    actions = tuple(a.model_copy(update={"hypothesis_id": None}) for a in answer.actions)
    return ReportNarrative(
        summary=answer.summary, actions=actions, open_questions=answer.open_questions
    )
