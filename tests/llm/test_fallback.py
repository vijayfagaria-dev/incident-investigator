import pytest

from investigator.llm.fallback import FallbackGateway
from investigator.llm.gateway import ModelRateLimited, ModelUnavailable
from investigator.tracing import MemoryTracer, ModelFellBack

from .test_retry import REPLY, REQUEST, FlakyGateway


def fallback(main: FlakyGateway, backup: FlakyGateway, tracer: MemoryTracer) -> FallbackGateway:
    return FallbackGateway(main, backup, main_model="nemotron", backup_model="glm", tracer=tracer)


async def test_the_backup_is_not_asked_while_the_main_model_answers() -> None:
    main, backup, tracer = FlakyGateway(), FlakyGateway(), MemoryTracer()

    reply = await fallback(main, backup, tracer).complete(REQUEST)

    assert reply is REPLY
    assert (main.calls, backup.calls) == (1, 0)
    assert tracer.of_type(ModelFellBack) == []


async def test_a_request_the_main_model_still_fails_goes_to_the_backup() -> None:
    main, backup, tracer = FlakyGateway(ModelRateLimited("429")), FlakyGateway(), MemoryTracer()

    reply = await fallback(main, backup, tracer).complete(REQUEST)

    assert reply is REPLY
    assert (main.calls, backup.calls) == (1, 1)
    [switch] = tracer.of_type(ModelFellBack)
    assert (switch.purpose, switch.failed_model, switch.backup_model, switch.error) == (
        "test",
        "nemotron",
        "glm",
        "ModelRateLimited: 429",
    )


async def test_the_backup_s_own_failure_is_what_the_caller_sees() -> None:
    main = FlakyGateway(ModelRateLimited("429"))
    backup = FlakyGateway(ModelUnavailable("502"))

    with pytest.raises(ModelUnavailable, match="502"):
        await fallback(main, backup, MemoryTracer()).complete(REQUEST)
