"""One agent's tool loop and conclusion, against a scripted model and the real tools on D2."""

import pytest

from investigator.domain.base import DomainModel
from investigator.domain.runs import FinishReason, StopReason
from investigator.domain.tools import ErrorKind, ToolName, ToolStatus
from investigator.llm.gateway import StructuredOutputError
from investigator.llm.messages import Role
from investigator.runtime.agent_loop import STEP_LIMIT, TRUNCATED, AgentLoop, AgentSpec
from investigator.runtime.budget import Budget, BudgetLimits
from investigator.tools.executor import ToolExecutor
from investigator.tools.registry import build_tools
from investigator.world.dataset import Dataset

from ..scripted import ScriptedGateway, answer, call, say

CHANGES = {"start": "2026-10-20T09:00:00Z", "end": "2026-10-20T10:30:00Z"}
LOGS = {
    "service": "payments-service",
    "start": "2026-10-20T10:00:00Z",
    "end": "2026-10-20T10:30:00Z",
}


class Finding(DomainModel):
    trigger: str
    confidence: float


SPEC = AgentSpec(
    role="investigator",
    system_prompt="Find the cause.",
    output_model=Finding,
    tools=(ToolName.QUERY_LOGS, ToolName.GET_CHANGE_HISTORY),
    max_steps=3,
)


def loop(dataset: Dataset, gateway: ScriptedGateway, budget: Budget | None = None) -> AgentLoop:
    registry = build_tools(dataset.telemetry("D2"), dataset.topology, dataset.history())
    return AgentLoop(gateway, ToolExecutor(registry), budget or Budget(BudgetLimits()))


async def test_parallel_tool_calls_feed_back_and_the_conclusion_is_parsed(dataset: Dataset) -> None:
    gateway = ScriptedGateway(
        [
            call(("get_change_history", CHANGES), ("query_logs", LOGS), tokens=50),
            say("The pool shrank to 5 just before the errors."),
            answer({"trigger": "chg:2290", "confidence": 0.8}),
        ]
    )
    budget = Budget(BudgetLimits())

    run = await loop(dataset, gateway, budget).run(SPEC, "Checkout is failing.")

    assert run.output == Finding(trigger="chg:2290", confidence=0.8)
    assert run.stop_reason is StopReason.CONCLUDED
    assert [r.tool for r in run.tool_results] == ["get_change_history", "query_logs"]
    assert all(r.status is ToolStatus.OK for r in run.tool_results)
    stats = budget.stats(rounds=1)
    assert (stats.model_calls, stats.tool_calls, stats.tokens) == (3, 2, 140)
    assert sum(m.role is Role.TOOL for m in gateway.requests[2].messages) == 2
    assert gateway.requests[0].tools
    assert not gateway.requests[2].tools
    assert gateway.requests[2].response_schema == Finding.model_json_schema()


async def test_bad_calls_come_back_as_errors_the_agent_can_correct(dataset: Dataset) -> None:
    gateway = ScriptedGateway(
        [
            call(("query_logs", "{not json"), ("query_metrics", {"service": "payments-service"})),
            say("ok"),
            answer({"trigger": "unknown", "confidence": 0.1}),
        ]
    )

    run = await loop(dataset, gateway).run(SPEC, "Checkout is failing.")

    malformed, forbidden = run.tool_results
    assert malformed.error is not None
    assert "not valid JSON" in malformed.error.message
    assert forbidden.error is not None
    assert forbidden.error.kind is ErrorKind.INVALID_QUERY
    assert "available tools: query_logs, get_change_history" in forbidden.error.message


async def test_running_out_of_steps_still_concludes(dataset: Dataset) -> None:
    gateway = ScriptedGateway(
        [call(("get_change_history", CHANGES)) for _ in range(3)]
        + [answer({"trigger": "chg:2290", "confidence": 0.5})]
    )

    run = await loop(dataset, gateway).run(SPEC, "Checkout is failing.")

    assert run.stop_reason is StopReason.STEP_LIMIT
    assert gateway.requests[-1].messages[-1].content.startswith(STEP_LIMIT)
    assert sum(r.cached for r in run.tool_results) == 2


async def test_a_bad_conclusion_gets_one_repair_attempt(dataset: Dataset) -> None:
    repaired = ScriptedGateway(
        [
            say("done"),
            say("chg:2290, fairly sure"),
            answer({"trigger": "chg:2290", "confidence": 0.7}),
        ]
    )
    hopeless = ScriptedGateway([say("done"), say("no idea"), say("still no JSON")])

    run = await loop(dataset, repaired).run(SPEC, "Checkout is failing.")
    assert run.output.trigger == "chg:2290"
    assert "not usable" in repaired.requests[-1].messages[-1].content

    with pytest.raises(StructuredOutputError):
        await loop(dataset, hopeless).run(SPEC, "Checkout is failing.")


async def test_a_spent_budget_skips_exploration_but_keeps_the_reserve_to_conclude(
    dataset: Dataset,
) -> None:
    budget = Budget(BudgetLimits(model_calls=3, reserve_model_calls=3))
    gateway = ScriptedGateway([answer({"trigger": "unknown", "confidence": 0.0})])

    run = await loop(dataset, gateway, budget).run(SPEC, "Checkout is failing.")

    assert run.stop_reason is StopReason.BUDGET
    assert run.tool_results == ()
    assert len(gateway.requests) == 1


async def test_tool_calls_beyond_the_budget_are_refused(dataset: Dataset) -> None:
    budget = Budget(BudgetLimits(tool_calls=1))
    gateway = ScriptedGateway(
        [
            call(("get_change_history", CHANGES), ("query_logs", LOGS)),
            answer({"trigger": "chg:2290", "confidence": 0.5}),
        ]
    )

    run = await loop(dataset, gateway, budget).run(SPEC, "Checkout is failing.")

    first, second = run.tool_results
    assert first.status is ToolStatus.OK
    assert second.error is not None
    assert second.error.kind is ErrorKind.REFUSED
    assert run.stop_reason is StopReason.BUDGET


async def test_a_truncated_conclusion_is_retried_with_a_request_to_be_brief(
    dataset: Dataset,
) -> None:
    cut_off = say('{"trigger": "chg:22')
    cut_off = cut_off.model_copy(update={"finish_reason": FinishReason.LENGTH})
    gateway = ScriptedGateway(
        [say("done"), cut_off, answer({"trigger": "chg:2290", "confidence": 0.7})]
    )

    run = await loop(dataset, gateway).run(SPEC, "Checkout is failing.")

    assert run.output.trigger == "chg:2290"
    assert gateway.requests[-1].messages[-1].content == TRUNCATED
