"""Whole investigations with a scripted model and the real tools on incident D2."""

from collections.abc import Callable

from investigator.agents.outputs import (
    Assessment,
    Findings,
    FollowUpPlan,
    HypothesisSet,
    InvestigationPlan,
    PlannedTask,
    ReportNarrative,
    VerdictDraft,
)
from investigator.domain.causes import Outcome
from investigator.domain.investigation import (
    AgentRole,
    EvidenceDomain,
    EvidenceRequestDraft,
    HypothesisDraft,
    ObservationDraft,
    Verdict,
)
from investigator.domain.report import Report
from investigator.domain.runs import TaskState
from investigator.investigation.config import InvestigationConfig
from investigator.investigation.run import MultiAgentInvestigator
from investigator.llm.messages import ChatRequest, ChatResponse
from investigator.tools.registry import build_tools
from investigator.tracing import (
    AgentCommitted,
    MemoryTracer,
    RoundEnded,
    TaskFinished,
    TaskStarted,
)
from investigator.world.dataset import Dataset

from ..scripted import ScriptedGateway, answer, call, say
from .conftest import DECOY, POOL_CHANGE, RoleScript, at, observation_id

OBSERVE = AgentRole.OBSERVABILITY
DEPEND = AgentRole.DEPENDENCY

PLAN = InvestigationPlan(
    rationale="checkout path",
    tasks=(
        PlannedTask(
            agent=OBSERVE,
            focus="What fails on payments?",
            services=("payments-service",),
            start=at("09:00"),
            end=at("10:20"),
        ),
        PlannedTask(
            agent=DEPEND,
            focus="What changed?",
            services=("payments-service", "notification-service"),
            start=at("09:00"),
            end=at("10:20"),
        ),
    ),
)
DB_QUESTION = "Is postgres-payments overloaded?"


def metric(service: str, name: str) -> dict[str, str]:
    return {"service": service, "metric": name, "start": at("09:30"), "end": at("10:20")}


def hypotheses(round_no: int) -> Callable[[ChatRequest], ChatResponse]:
    def reply(request: ChatRequest) -> ChatResponse:
        pool = observation_id(request, "pool max fell")
        change = observation_id(request, "cut the pool")
        deploy = observation_id(request, "notification-service deployed")
        if round_no == 1:
            return answer(
                HypothesisSet(
                    hypotheses=(
                        HypothesisDraft(
                            root_cause=POOL_CHANGE,
                            mechanism="pool too small",
                            supporting=(pool, change),
                            confidence=0.6,
                        ),
                        HypothesisDraft(
                            root_cause=DECOY,
                            mechanism="new renderer",
                            supporting=(deploy,),
                            confidence=0.3,
                        ),
                    )
                )
            )
        quiet_db = observation_id(request, "postgres-payments connections fell")
        return answer(
            HypothesisSet(
                hypotheses=(
                    HypothesisDraft(
                        id="HYP-1",
                        root_cause=POOL_CHANGE,
                        mechanism="pool too small",
                        supporting=(pool, change, quiet_db),
                        confidence=0.9,
                    ),
                    HypothesisDraft(
                        id="HYP-2",
                        root_cause=DECOY,
                        mechanism="new renderer",
                        supporting=(deploy,),
                        confidence=0.1,
                    ),
                )
            )
        )

    return reply


def two_round_script() -> RoleScript:
    return RoleScript(
        {
            AgentRole.ORCHESTRATOR: [
                call(("get_service_dependencies", {"service": "payments-service"})),
                say("planned"),
                answer(PLAN),
                answer(
                    FollowUpPlan(
                        tasks=(
                            PlannedTask(
                                agent=OBSERVE,
                                focus=DB_QUESTION,
                                services=("postgres-payments",),
                                start=at("09:30"),
                                end=at("10:20"),
                            ),
                        )
                    )
                ),
            ],
            OBSERVE: [
                call(("query_metrics", metric("payments-service", "db_pool_max_connections"))),
                say("read it"),
                answer(
                    Findings(
                        summary="pool",
                        observations=(
                            ObservationDraft(
                                statement="pool max fell to 5 at 10:03",
                                artifacts=("metric:payments-service/db_pool_max_connections",),
                            ),
                        ),
                    )
                ),
                call(("query_metrics", metric("postgres-payments", "active_connections"))),
                say("read it"),
                answer(
                    Findings(
                        summary="db",
                        observations=(
                            ObservationDraft(
                                statement="postgres-payments connections fell by half",
                                artifacts=("metric:postgres-payments/active_connections",),
                            ),
                        ),
                    )
                ),
            ],
            DEPEND: [
                call(("get_change_history", {"start": at("09:00"), "end": at("10:20")})),
                say("listed"),
                answer(
                    Findings(
                        summary="changes",
                        observations=(
                            ObservationDraft(
                                statement="chg:2290 cut the pool from 50 to 5 at 10:02",
                                artifacts=("chg:2290",),
                            ),
                            ObservationDraft(
                                statement="notification-service deployed v3.8.1 at 10:02",
                                artifacts=("chg:2291",),
                            ),
                        ),
                    )
                ),
            ],
            AgentRole.REASONING: [say("weighing"), hypotheses(1), say("weighing"), hypotheses(2)],
            AgentRole.CRITIC: [
                answer(
                    Assessment(
                        verdicts=(
                            VerdictDraft(
                                hypothesis_id="HYP-1",
                                verdict=Verdict.CHALLENGE,
                                reason="is the database fine?",
                            ),
                            VerdictDraft(
                                hypothesis_id="HYP-2",
                                verdict=Verdict.REJECT,
                                reason="not on the path",
                            ),
                        ),
                        requests=(
                            EvidenceRequestDraft(
                                question=DB_QUESTION,
                                domain=EvidenceDomain.OBSERVABILITY,
                                service="postgres-payments",
                            ),
                        ),
                    )
                ),
                answer(
                    Assessment(
                        verdicts=(
                            VerdictDraft(
                                hypothesis_id="HYP-1",
                                verdict=Verdict.ACCEPT,
                                reason="database is quiet",
                            ),
                            VerdictDraft(
                                hypothesis_id="HYP-2",
                                verdict=Verdict.REJECT,
                                reason="not on the path",
                            ),
                        )
                    )
                ),
            ],
            AgentRole.REPORTING: [answer(ReportNarrative(summary="The pool was cut to 5."))],
        }
    )


async def investigate(
    dataset: Dataset, script: RoleScript, tracer: MemoryTracer, **config: object
) -> Report:
    world = dataset.telemetry("D2")
    tools = build_tools(world, dataset.topology, dataset.history())
    investigator = MultiAgentInvestigator(
        ScriptedGateway(script), tools, InvestigationConfig.model_validate(config), tracer
    )
    return await investigator.investigate(dataset.incident_report("D2"))


async def test_a_critic_request_drives_a_second_round_that_settles_the_cause(
    dataset: Dataset,
) -> None:
    script, tracer = two_round_script(), MemoryTracer()

    report = await investigate(dataset, script, tracer)

    assert report.outcome is Outcome.CONCLUSIVE
    assert report.root_cause == POOL_CHANGE
    assert report.termination == "the critic accepted HYP-1"
    assert report.stats.rounds == 2
    top = report.hypotheses[0]
    assert (top.hypothesis.id, top.hypothesis.version, top.verdict) == ("HYP-1", 2, Verdict.ACCEPT)
    assert "metric:postgres-payments/active_connections" in {
        a for f in report.facts for a in f.artifacts
    }
    assert script.leftover() == {}


async def test_each_round_closes_with_the_standings_and_the_stop_decision(
    dataset: Dataset,
) -> None:
    tracer = MemoryTracer()

    await investigate(dataset, two_round_script(), tracer)

    first, second = tracer.of_type(RoundEnded)
    assert (first.round, first.stop_reason) == (1, None)
    assert [s.verdict for s in first.standings] == [Verdict.CHALLENGE, Verdict.REJECT]
    assert second.stop_reason == "the critic accepted HYP-1"
    leader = second.standings[0]
    assert (leader.hypothesis_id, leader.version, leader.verdict) == ("HYP-1", 2, Verdict.ACCEPT)


async def test_specialists_in_a_round_run_in_parallel_and_every_commit_is_traced(
    dataset: Dataset,
) -> None:
    tracer = MemoryTracer()

    await investigate(dataset, two_round_script(), tracer)

    order = [
        (type(e).__name__, e.task_id)
        for e in tracer.events
        if isinstance(e, TaskStarted | TaskFinished)
    ]
    first_finish = next(
        i for i, (kind, _) in enumerate(order) if kind == "TaskFinished" and _ != "plan"
    )
    started_before = {task for kind, task in order[:first_finish] if kind == "TaskStarted"}
    assert {"r1-observability-1", "r1-dependency-2"} <= started_before
    assert ("TaskStarted", "r2-observability-3") in order
    roles = {e.role for e in tracer.of_type(AgentCommitted)}
    assert roles == {"orchestrator", "observability", "dependency", "reasoning", "critic"}


async def test_a_failed_plan_falls_back_to_watching_the_reported_services(dataset: Dataset) -> None:
    tracer = MemoryTracer()
    script = RoleScript(
        {
            AgentRole.ORCHESTRATOR: [
                say("no tools needed"),
                say("plan: look around"),
                say("still prose"),
            ],
            OBSERVE: [say("nothing"), answer(Findings(summary="nothing to add"))],
            DEPEND: [say("nothing"), answer(Findings(summary="nothing to add"))],
            AgentRole.REASONING: [
                say("unsure"),
                answer(
                    HypothesisSet(
                        hypotheses=(
                            HypothesisDraft(
                                root_cause=POOL_CHANGE, mechanism="guess", confidence=0.2
                            ),
                        )
                    )
                ),
            ],
            AgentRole.CRITIC: [
                answer(
                    Assessment(
                        verdicts=(
                            VerdictDraft(
                                hypothesis_id="HYP-1", verdict=Verdict.REJECT, reason="no evidence"
                            ),
                        )
                    )
                )
            ],
            AgentRole.REPORTING: [answer(ReportNarrative(summary="Inconclusive."))],
        }
    )

    report = await investigate(dataset, script, tracer, task_attempts=1, max_rounds=1)

    plan = next(e for e in tracer.of_type(TaskFinished) if e.task_id == "plan")
    assert plan.state is TaskState.FAILED
    assert any(g.scope == "plan" for g in report.gaps)
    assert ("TaskStarted", "r1-dependency-2") in [
        (type(e).__name__, getattr(e, "task_id", "")) for e in tracer.events
    ]
    assert report.outcome is Outcome.INCONCLUSIVE
    assert "HYP-1 cites no supporting observations" in report.outcome_reasons


async def test_failing_reasoning_and_reporting_still_yield_an_honest_report(
    dataset: Dataset,
) -> None:
    def garbage(_request: ChatRequest) -> ChatResponse:
        return say("I cannot produce JSON today.")

    script = RoleScript(
        {
            AgentRole.ORCHESTRATOR: [
                call(("get_service_dependencies", {"service": "payments-service"})),
                say("ok"),
                answer(PLAN),
            ],
            OBSERVE: [say("nothing"), answer(Findings(summary="nothing"))],
            DEPEND: [say("nothing"), answer(Findings(summary="nothing"))],
            AgentRole.REASONING: [garbage] * 3,
            AgentRole.REPORTING: [garbage] * 2,
        }
    )

    report = await investigate(dataset, script, MemoryTracer(), task_attempts=1)

    assert report.outcome is Outcome.INCONCLUSIVE
    assert report.root_cause is None
    assert report.outcome_reasons == ("no hypothesis was established",)
    assert report.summary.startswith("The investigation was inconclusive")
    assert any(g.scope == "hypotheses" for g in report.gaps)
