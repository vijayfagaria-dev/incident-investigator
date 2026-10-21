"""The OpenAI-compatible gateway, against a fake completions endpoint."""

from types import SimpleNamespace
from typing import Any

import httpx2
import openai
import pytest

from investigator.domain.runs import FinishReason
from investigator.llm.gateway import ModelRateLimited, ModelRejected, ModelUnavailable
from investigator.llm.messages import ChatRequest, Message, Role, ToolCallRequest, ToolDefinition
from investigator.llm.openai_compat import OpenAICompatGateway
from investigator.llm.profiles import PROFILES
from investigator.tracing import MemoryTracer, ModelCalled

REQUEST = httpx2.Request("POST", "https://integrate.api.nvidia.com/v1/chat/completions")


def completion(content: str = "", tool_calls: list[Any] | None = None, finish: str = "stop") -> Any:
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    usage = SimpleNamespace(prompt_tokens=120, completion_tokens=30)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason=finish)],
        usage=usage,
        model="served-model",
    )


class FakeCompletions:
    def __init__(self, reply: Any = None, error: Exception | None = None) -> None:
        self.reply = reply if reply is not None else completion("ok")
        self.error = error
        self.params: dict[str, Any] = {}

    async def create(self, **params: Any) -> Any:
        self.params = params
        if self.error is not None:
            raise self.error
        return self.reply


def gateway(
    completions: FakeCompletions, tracer: MemoryTracer | None = None
) -> OpenAICompatGateway:
    return OpenAICompatGateway(PROFILES["nvidia"], completions, tracer=tracer)


async def test_requests_carry_tools_schema_and_profile_sampling() -> None:
    fake = FakeCompletions()
    await gateway(fake).complete(
        ChatRequest(
            purpose="test",
            messages=(
                Message.user("why?"),
                Message(
                    role=Role.ASSISTANT,
                    tool_calls=(ToolCallRequest(id="t1", name="query_logs", arguments="{}"),),
                ),
                Message.tool_result("t1", '{"status": "ok"}'),
            ),
            tools=(
                ToolDefinition(name="query_logs", description="d", parameters={"type": "object"}),
            ),
            response_schema={"type": "object"},
        )
    )

    params = fake.params
    assert params["model"] == PROFILES["nvidia"].model
    assert params["tool_choice"] == "auto"
    assert params["tools"][0]["function"]["name"] == "query_logs"
    assert params["response_format"]["json_schema"]["strict"] is True
    assert params["temperature"] == 1.0
    assert params["messages"][1]["tool_calls"][0]["function"]["name"] == "query_logs"
    assert params["messages"][2] == {
        "role": "tool",
        "content": '{"status": "ok"}',
        "tool_call_id": "t1",
    }


async def test_responses_are_mapped_to_provider_neutral_types() -> None:
    call = SimpleNamespace(
        id="c1", function=SimpleNamespace(name="query_logs", arguments='{"a": 1}')
    )
    tracer = MemoryTracer()
    fake = FakeCompletions(completion(tool_calls=[call], finish="tool_calls"))

    response = await gateway(fake, tracer).complete(
        ChatRequest(purpose="observability", messages=(Message.user("x"),))
    )

    assert response.finish_reason is FinishReason.TOOL_CALLS
    assert response.message.tool_calls == (
        ToolCallRequest(id="c1", name="query_logs", arguments='{"a": 1}'),
    )
    assert response.usage.total_tokens == 150
    assert response.model == "served-model"
    [event] = tracer.of_type(ModelCalled)
    assert (event.purpose, event.tool_calls, event.prompt_tokens) == ("observability", 1, 120)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (openai.APIConnectionError(request=REQUEST), ModelUnavailable),
        (
            openai.RateLimitError(
                "slow down", response=httpx2.Response(429, request=REQUEST), body=None
            ),
            ModelRateLimited,
        ),
        (
            openai.BadRequestError(
                "bad", response=httpx2.Response(400, request=REQUEST), body=None
            ),
            ModelRejected,
        ),
        (
            openai.InternalServerError(
                "boom", response=httpx2.Response(503, request=REQUEST), body=None
            ),
            ModelUnavailable,
        ),
    ],
)
async def test_provider_errors_become_model_errors(
    error: Exception, expected: type[Exception]
) -> None:
    tracer = MemoryTracer()
    with pytest.raises(expected):
        await gateway(FakeCompletions(error=error), tracer).complete(
            ChatRequest(purpose="test", messages=(Message.user("x"),))
        )
    assert tracer.of_type(ModelCalled)[0].error is not None


async def test_a_rejected_schema_falls_back_to_plain_json_mode() -> None:
    class RejectsSchemas(FakeCompletions):
        async def create(self, **params: Any) -> Any:
            self.params = params
            if params["response_format"]["type"] == "json_schema":
                raise openai.BadRequestError(
                    "unsupported schema", response=httpx2.Response(400, request=REQUEST), body=None
                )
            return self.reply

    fake = RejectsSchemas(completion('{"a": 1}'))
    request = ChatRequest(
        purpose="t", messages=(Message.user("x"),), response_schema={"type": "object"}
    )
    target = gateway(fake)

    first = await target.complete(request)
    await target.complete(request)

    assert first.message.content == '{"a": 1}'
    assert fake.params["response_format"] == {"type": "json_object"}
