"""One incident investigated by the agent team, as a LangGraph graph.

Plan and list every recent change, then rounds of: specialists gathering evidence in
parallel, following their leads, forming hypotheses and critiquing them, until the critic
accepts, a limit is reached or nothing more is worth checking. Each agent step gets a time
limit and a second attempt, and a failed agent becomes an evidence gap rather than a crash.
Agents never touch the board: the run commits what they return, one result at a time.
"""

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from investigator.agents.critic import CriticAgent, observed_changes, rule_objections
from investigator.agents.orchestrator import Orchestrator
from investigator.agents.outputs import InvestigationPlan, PlannedTask, ReportNarrative
from investigator.agents.reasoning import ReasoningAgent
from investigator.agents.reporting import ReportingAgent
from investigator.agents.specialists import Specialist
from investigator.domain.incident import IncidentReport
from investigator.domain.investigation import AgentRole, GapDraft
from investigator.domain.report import Report
from investigator.domain.runs import TaskState
from investigator.investigation.assembly import assemble, fallback_narrative
from investigator.investigation.census import take_change_census
from investigator.investigation.config import InvestigationConfig
from investigator.investigation.planning import FollowUpPlanner, fallback_plan
from investigator.investigation.policy import (
    decide_outcome,
    requests_to_pursue,
    standings,
    stop_reason,
)
from investigator.llm.gateway import ModelGateway
from investigator.runtime.agent_loop import AgentLoop, AgentRun
from investigator.runtime.blackboard import Blackboard, Commit
from investigator.runtime.budget import Budget
from investigator.runtime.tasks import TaskResult, run_task
from investigator.tools.executor import ToolExecutor
from investigator.tools.registry import ToolRegistry
from investigator.tracing import AgentCommitted, RoundEnded, Tracer

Job = Callable[[], Awaitable[Any]]


@dataclass(frozen=True)
class MultiAgentInvestigator:
    """The agent team. Each investigation gets a fresh board, budget and tool cache."""

    gateway: ModelGateway
    tools: ToolRegistry
    config: InvestigationConfig
    tracer: Tracer

    async def investigate(self, incident: IncidentReport) -> Report:
        budget = Budget(self.config.budget)
        executor = ToolExecutor(self.tools, tracer=self.tracer)
        loop = AgentLoop(self.gateway, executor, budget)
        return await InvestigationRun(
            incident, loop, executor, budget, self.config, self.tracer
        ).execute()


def commit_traced(
    board: Blackboard,
    tracer: Tracer,
    task_id: str,
    role: str,
    output: dict[str, Any],
    apply: Callable[[], Commit],
    gap: tuple[str, str],
) -> Commit | None:
    """Apply an agent's result to the board and trace it; a faulty commit becomes a gap.

    ``gap`` names the tool and scope the gap is recorded under if the commit fails.
    """
    try:
        commit = apply()
    except Exception as exc:  # The investigation must survive a bad commit.
        tool, scope = gap
        board.add_findings(task_id, gaps=[GapDraft(tool=tool, scope=scope, reason=repr(exc))])
        tracer.record(AgentCommitted(task_id=task_id, role=role, output=output, error=repr(exc)))
        return None
    tracer.record(
        AgentCommitted(
            task_id=task_id,
            role=role,
            output=output,
            accepted=commit.accepted,
            problems=commit.problems,
        )
    )
    return commit


class _RunState(TypedDict, total=False):
    planned: list[PlannedTask]
    """Tasks for the next round of gathering."""
    assignments: list["_Assignment"]
    round_no: int
    observations_before: int
    termination: str
    """Why the investigation stops; set once it should."""
    report: Report


class _Assignment(TypedDict):
    task_id: str
    task: PlannedTask


class InvestigationRun:
    def __init__(
        self,
        incident: IncidentReport,
        loop: AgentLoop,
        executor: ToolExecutor,
        budget: Budget,
        config: InvestigationConfig,
        tracer: Tracer,
    ) -> None:
        self._orchestrator = Orchestrator(loop)
        self._specialists = {
            role: Specialist(loop, role, config.specialist_steps)
            for role in (AgentRole.OBSERVABILITY, AgentRole.DEPENDENCY)
        }
        self._reasoning = ReasoningAgent(loop, config.reasoning_steps)
        self._critic = CriticAgent(loop)
        self._reporting = ReportingAgent(loop)
        self._tracer = tracer
        self._executor = executor
        self._budget = budget
        self._config = config
        self._board = Blackboard(incident)
        self._followups = FollowUpPlanner((), incident.reported_at, incident.reported_at)
        self._done: list[PlannedTask] = []
        self._seen_leads: set[str] = set()

    async def execute(self) -> Report:
        graph = StateGraph(_RunState)
        graph.add_node("plan", self._plan_and_census)
        graph.add_node("start_round", self._start_round)
        graph.add_node("gather", self._gather_one, input_schema=_Assignment)
        graph.add_node("leads", self._leads)
        graph.add_node("follow_lead", self._gather_one, input_schema=_Assignment)
        graph.add_node("hypothesise", self._hypothesise)
        graph.add_node("critique", self._critique)
        graph.add_node("close_round", self._close_round)
        graph.add_node("follow_up", self._follow_up)
        graph.add_node("report", self._write_report)
        graph.add_edge(START, "plan")
        graph.add_conditional_edges("plan", _report_if_stopping("start_round"))
        graph.add_conditional_edges("start_round", _fan_out("gather"), ["gather"])
        graph.add_edge("gather", "leads")
        graph.add_conditional_edges(
            "leads",
            _fan_out("follow_lead", otherwise="hypothesise"),
            ["follow_lead", "hypothesise"],
        )
        graph.add_edge("follow_lead", "hypothesise")
        graph.add_edge("hypothesise", "critique")
        graph.add_edge("critique", "close_round")
        graph.add_conditional_edges("close_round", _report_if_stopping("follow_up"))
        graph.add_conditional_edges("follow_up", _report_if_stopping("start_round"))
        graph.add_edge("report", END)
        settings: RunnableConfig = {
            "max_concurrency": self._config.concurrency,
            "recursion_limit": 10 * self._config.max_rounds + 10,
        }
        start: _RunState = {}
        final = await graph.compile().ainvoke(start, settings)
        report: Report = final["report"]
        return report

    async def _plan_and_census(self, state: _RunState) -> _RunState:
        try:
            plan = await self._plan()
        except ValueError as exc:
            return {"termination": f"no investigation was possible: {exc}"}
        start, end = min(t.start for t in plan.tasks), max(t.end for t in plan.tasks)
        services = sorted({s for t in plan.tasks for s in t.services})
        self._followups = FollowUpPlanner(services, start, end)
        await take_change_census(self._executor, self._board, start, end)
        return {"planned": list(plan.tasks)}

    async def _start_round(self, state: _RunState) -> _RunState:
        round_no = self._board.start_round()
        return {
            "round_no": round_no,
            "observations_before": len(self._board.view().observations),
            "assignments": self._assign(state["planned"]),
        }

    def _assign(self, tasks: Sequence[PlannedTask]) -> list[_Assignment]:
        """Give each task its id, such as r1-observability-1, and count it as done."""
        assignments = []
        for index, task in enumerate(tasks, start=1):
            task_id = f"r{self._board.round}-{task.agent}-{len(self._done) + index}"
            assignments.append(_Assignment(task_id=task_id, task=task))
        self._done += tasks
        return assignments

    async def _gather_one(self, state: _Assignment) -> _RunState:
        task, task_id = state["task"], state["task_id"]
        agent = self._specialists[task.agent]
        requests = self._board.view().requests
        request = next((r for r in requests if r.question == task.focus), None)
        result = await self._run_one(
            task_id, agent.role, lambda: agent.run(agent.brief(self._board.view(), task, request))
        )
        if result.state is TaskState.SUCCEEDED:
            self._commit(
                result, agent.role, lambda: agent.commit(self._board, result.value, result.task_id)
            )
        else:
            self._record_failure(result, scope=task.focus)
        return {}

    async def _leads(self, state: _RunState) -> _RunState:
        new_leads = [lead for lead in self._board.view().leads if lead.id not in self._seen_leads]
        self._seen_leads.update(lead.id for lead in new_leads)
        lead_tasks = self._followups.from_leads(new_leads, self._done, self._config.max_lead_tasks)
        return {"assignments": self._assign(lead_tasks)}

    async def _close_round(self, state: _RunState) -> _RunState:
        view = self._board.view()
        new_observations = len(view.observations) - state["observations_before"]
        reason = stop_reason(view, self._budget, new_observations, self._config.max_rounds)
        self._tracer.record(
            RoundEnded(round=view.round, standings=standings(view), stop_reason=reason)
        )
        return {"termination": reason} if reason else {}

    async def _follow_up(self, state: _RunState) -> _RunState:
        tasks = await self._next_tasks(state["round_no"])
        if not tasks:
            return {"termination": "no requested evidence was worth gathering"}
        return {"planned": tasks}

    async def _write_report(self, state: _RunState) -> _RunState:
        return {"report": await self._report(state["termination"])}

    async def _plan(self) -> InvestigationPlan:
        result = await self._run_one(
            "plan", AgentRole.ORCHESTRATOR, lambda: self._orchestrator.plan(self._board.view())
        )
        if result.state is TaskState.SUCCEEDED:
            run: AgentRun[InvestigationPlan] = result.value
            self._board.record_tool_results(run.tool_results)
            self._trace_plan(result.task_id, run.output.model_dump(mode="json"), run.output.tasks)
            return run.output
        self._board.add_findings(
            "plan",
            gaps=[GapDraft(tool="orchestrator", scope="plan", reason=result.error or "failed")],
        )
        return await fallback_plan(self._executor, self._board)

    async def _hypothesise(self, state: _RunState) -> _RunState:
        reasoning = self._reasoning
        result = await self._run_one(
            f"r{self._board.round}-reasoning",
            reasoning.role,
            lambda: reasoning.run(reasoning.brief(self._board.view())),
        )
        if result.state is TaskState.SUCCEEDED:
            self._commit(
                result,
                reasoning.role,
                lambda: reasoning.commit(self._board, result.value, result.task_id),
            )
        else:
            self._record_failure(result, scope="hypotheses")
        return {}

    async def _critique(self, state: _RunState) -> _RunState:
        critic = self._critic
        view = self._board.view()
        if not view.hypotheses:
            return {}
        found = rule_objections(view, observed_changes(self._board.tool_results()))
        result = await self._run_one(
            f"r{view.round}-critic",
            critic.role,
            lambda: critic.run(critic.brief(self._board.view(), found)),
        )
        succeeded = result.state is TaskState.SUCCEEDED
        if not succeeded:
            self._record_failure(result, scope="critique")

        def review() -> Commit:
            made = critic.review(self._board, result.value if succeeded else None, found)
            verdicts = tuple(f"{h}: {v}" for h, v in made.verdicts.items())
            return Commit(accepted=(*verdicts, *(r.id for r in made.requests)))

        self._commit(result, critic.role, review)
        return {}

    async def _next_tasks(self, round_no: int) -> list[PlannedTask]:
        view = self._board.view()
        requests = requests_to_pursue(view, round_no)
        if not requests:
            return []
        limit = self._config.max_followup_tasks
        result = await self._run_one(
            f"r{round_no}-followup",
            AgentRole.ORCHESTRATOR,
            lambda: self._orchestrator.follow_up(self._board.view(), requests, self._done, limit),
        )
        if result.state is TaskState.SUCCEEDED:
            chosen = list(result.value.output.tasks[:limit])
            self._trace_plan(result.task_id, result.value.output.model_dump(mode="json"), chosen)
            return chosen
        self._record_failure(result, scope="follow-up planning")
        return self._followups.from_requests(requests, self._done, limit)

    async def _report(self, termination: str) -> Report:
        view = self._board.view()
        config = self._config
        decision = decide_outcome(view, config.min_confidence, config.min_margin)
        reporting = self._reporting
        # The reporting agent sees each hypothesis with its capped confidence.
        ranked = [
            c.hypothesis.model_copy(update={"confidence": c.confidence}) for c in decision.ranked
        ]
        result = await self._run_one(
            "report",
            reporting.role,
            lambda: reporting.run(
                reporting.brief(view, decision.outcome, decision.reasons, ranked, termination)
            ),
        )
        narrative: ReportNarrative = (
            result.value.output
            if result.state is TaskState.SUCCEEDED
            else fallback_narrative(decision, termination)
        )
        stats = self._budget.stats(rounds=view.round)
        return assemble(self._board.view(), decision, narrative, termination, stats)

    async def _run_one(self, task_id: str, label: str, job: Job) -> TaskResult:
        return await run_task(
            task_id,
            label,
            job,
            tracer=self._tracer,
            timeout_s=self._config.task_timeout_s,
            max_attempts=self._config.task_attempts,
            stop_reason=self._cancel_reason,
        )

    def _commit(self, result: TaskResult, role: str, apply: Callable[[], Commit]) -> None:
        output = result.value.output.model_dump(mode="json") if result.value else {}
        gap = (f"agent {result.task_id}", role)
        commit_traced(self._board, self._tracer, result.task_id, role, output, apply, gap)

    def _trace_plan(
        self, task_id: str, output: dict[str, Any], tasks: Sequence[PlannedTask]
    ) -> None:
        self._tracer.record(
            AgentCommitted(
                task_id=task_id,
                role=AgentRole.ORCHESTRATOR,
                output=output,
                accepted=tuple(f"{t.agent}: {t.focus}" for t in tasks),
            )
        )

    def _record_failure(self, result: TaskResult, scope: str) -> None:
        reason = result.error or result.state
        gap = GapDraft(tool=f"agent {result.task_id}", scope=scope, reason=reason)
        self._board.add_findings(result.task_id, gaps=[gap])

    def _cancel_reason(self) -> str | None:
        """Start no more agent work once even the concluding reserve is spent."""
        if self._budget.fully_spent():
            return "budget fully spent"
        if self._budget.elapsed_s() >= self._budget.limits.wall_clock_s * 1.5:
            return "time budget overrun"
        return None


def _report_if_stopping(otherwise: str) -> Callable[[_RunState], str]:
    def route(state: _RunState) -> str:
        return "report" if state.get("termination") else otherwise

    return route


def _fan_out(node: str, otherwise: str | None = None) -> Callable[[_RunState], list[Send] | str]:
    """Send each assigned task to ``node``, all at once; with none, go to ``otherwise``."""

    def route(state: _RunState) -> list[Send] | str:
        assignments = state.get("assignments", [])
        if not assignments and otherwise is not None:
            return otherwise
        return [Send(node, assignment) for assignment in assignments]

    return route
