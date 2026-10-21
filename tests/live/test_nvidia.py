"""Smoke test against the real NVIDIA endpoint. Run with ``uv run pytest -m live``."""

from pathlib import Path

import pytest

from investigator.domain.base import DomainModel
from investigator.domain.tools import ToolName
from investigator.llm.fallback import FallbackGateway
from investigator.llm.gateway import ModelGateway, ModelUnavailable
from investigator.llm.messages import ChatRequest, ChatResponse
from investigator.llm.openai_compat import OpenAICompatGateway
from investigator.llm.profiles import PROFILES, MissingCredentials, api_key
from investigator.runtime.agent_loop import AgentLoop, AgentSpec
from investigator.runtime.budget import Budget, BudgetLimits
from investigator.tools.executor import ToolExecutor
from investigator.tools.registry import build_tools
from investigator.tracing import MemoryTracer, ModelCalled, ModelFellBack
from investigator.world.dataset import Dataset

pytestmark = pytest.mark.live

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Conclusion(DomainModel):
    trigger_change_id: str
    root_cause_service: str
    reasoning: str


class Down:
    """A main model that never answers."""

    async def complete(self, request: ChatRequest) -> ChatResponse:
        raise ModelUnavailable("down for this test")


def connect(profile_name: str, tracer: MemoryTracer) -> OpenAICompatGateway:
    profile = PROFILES[profile_name]
    try:
        key = api_key(profile, env_file=ENV_FILE)
    except MissingCredentials as exc:
        pytest.skip(str(exc))
    return OpenAICompatGateway.connect(profile, key, tracer=tracer)


@pytest.fixture
def tracer() -> MemoryTracer:
    return MemoryTracer()


async def test_an_agent_uses_tools_and_concludes_in_the_requested_structure(
    dataset: Dataset, tracer: MemoryTracer
) -> None:
    await investigate_d2(dataset, connect("nvidia", tracer), tracer)


async def test_the_backup_model_carries_an_agent_when_the_main_one_is_down(
    dataset: Dataset, tracer: MemoryTracer
) -> None:
    backup = PROFILES[PROFILES["nvidia"].fallback or ""]
    gateway = FallbackGateway(
        Down(),
        connect(backup.name, tracer),
        main_model=PROFILES["nvidia"].model,
        backup_model=backup.model,
        tracer=tracer,
    )

    await investigate_d2(dataset, gateway, tracer)

    assert tracer.of_type(ModelFellBack)
    assert {call.model for call in tracer.of_type(ModelCalled)} == {backup.model}


async def investigate_d2(dataset: Dataset, gateway: ModelGateway, tracer: MemoryTracer) -> None:
    registry = build_tools(dataset.telemetry("D2"), dataset.topology, dataset.history())
    loop = AgentLoop(gateway, ToolExecutor(registry, tracer=tracer), Budget(BudgetLimits()))
    spec = AgentSpec(
        role="smoke",
        system_prompt=(
            "You are a site reliability engineer. Investigate with the tools before concluding. "
            "Check both runtime signals and recent changes."
        ),
        output_model=Conclusion,
        tools=(ToolName.QUERY_LOGS, ToolName.GET_CHANGE_HISTORY),
        max_steps=5,
    )

    run = await loop.run(
        spec,
        "Checkout requests to payments-service started failing at about 10:04 UTC on "
        "2026-10-20. Find the change that caused it.",
    )

    calls = tracer.of_type(ModelCalled)
    print(f"\nconclusion: {run.output}")
    print(f"tools used: {[r.tool for r in run.tool_results]}; stop: {run.stop_reason}")
    for call in calls:
        print(
            f"  {call.purpose}: {call.latency_ms:.0f} ms "
            f"(+{call.rate_limit_wait_ms:.0f} ms queued), "
            f"{call.prompt_tokens}+{call.completion_tokens} tokens, finish={call.finish_reason}"
        )
    assert run.tool_results
    assert run.output.trigger_change_id.startswith("chg:")
    assert all(call.error is None for call in calls)
