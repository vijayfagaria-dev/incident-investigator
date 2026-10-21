"""The single-agent baseline, with a scripted model and the real tools on incident D2."""

from investigator.agents.outputs import KeyedObservation, SoloAnswer
from investigator.domain.causes import CauseCategory, Outcome, RootCause
from investigator.domain.investigation import AgentRole, HypothesisDraft
from investigator.domain.report import Report
from investigator.domain.tools import ToolName
from investigator.investigation.config import InvestigationConfig
from investigator.llm.gateway import ModelRejected
from investigator.llm.messages import ChatRequest, ChatResponse
from investigator.systems import System, build_investigator
from investigator.tools.registry import build_tools
from investigator.tracing import AgentCommitted, MemoryTracer
from investigator.world.dataset import Dataset

from ..scripted import ScriptedGateway, answer, call, say

POOL = RootCause(
    service="payments-service", category=CauseCategory.CONFIG_CHANGE, trigger="chg:2290"
)
DECOY = RootCause(
    service="notification-service", category=CauseCategory.CODE_REGRESSION, trigger="chg:2291"
)
WINDOW = {"start": "2026-10-20T09:00:00Z", "end": "2026-10-20T10:20:00Z"}

ANSWER = SoloAnswer(
    summary="A config change shrank the payments pool.",
    observations=(
        KeyedObservation(
            key="F1",
            statement="pool max fell from 50 to 5 at 10:03",
            artifacts=("metric:payments-service/db_pool_max_connections",),
        ),
        KeyedObservation(key="F2", statement="chg:2290 cut the pool", artifacts=("chg:2290",)),
        KeyedObservation(key="F3", statement="notifications deployed", artifacts=("chg:2291",)),
        KeyedObservation(key="F4", statement="invented", artifacts=("log:made-up",)),
    ),
    hypotheses=(
        HypothesisDraft(
            root_cause=POOL, mechanism="pool", supporting=("F1", "F2"), confidence=0.85
        ),
        HypothesisDraft(root_cause=DECOY, mechanism="renderer", supporting=("F3",), confidence=0.1),
    ),
)


async def investigate(dataset: Dataset, gateway: ScriptedGateway, tracer: MemoryTracer) -> Report:
    tools = build_tools(dataset.telemetry("D2"), dataset.topology, dataset.history())
    investigator = build_investigator(System.SINGLE, gateway, tools, InvestigationConfig(), tracer)
    return await investigator.investigate(dataset.incident_report("D2"))


async def test_one_agent_gathers_evidence_and_the_shared_policy_decides(dataset: Dataset) -> None:
    gateway = ScriptedGateway(
        [
            call(
                ("query_metrics", {"service": "payments-service", **WINDOW}),
                ("get_change_history", WINDOW),
            ),
            say("enough"),
            answer(ANSWER),
        ]
    )
    tracer = MemoryTracer()

    report = await investigate(dataset, gateway, tracer)

    assert report.outcome is Outcome.CONCLUSIVE
    assert report.root_cause == POOL
    assert report.stats.rounds == 1
    assert report.termination == "the agent finished its investigation"
    cited = {a for fact in report.facts for a in fact.artifacts}
    assert cited == {"metric:payments-service/db_pool_max_connections", "chg:2290", "chg:2291"}
    [commit] = tracer.of_type(AgentCommitted)
    assert commit.role == AgentRole.SOLO
    assert any("invented" in problem for problem in commit.problems)
    assert {request.purpose for request in gateway.requests} == {AgentRole.SOLO}
    assert {tool.name for tool in gateway.requests[0].tools} == set(ToolName)


async def test_a_failed_agent_still_yields_an_inconclusive_report(dataset: Dataset) -> None:
    def refuse(_request: ChatRequest) -> ChatResponse:
        raise ModelRejected("400")

    report = await investigate(dataset, ScriptedGateway(refuse), MemoryTracer())

    assert report.outcome is Outcome.INCONCLUSIVE
    assert report.termination.startswith("the agent failed")
    assert report.hypotheses == ()
    assert [gap.scope for gap in report.gaps] == ["investigate"]
