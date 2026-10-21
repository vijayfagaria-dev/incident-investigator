import asyncio
from random import Random

import pytest

from investigator.domain.runs import FinishReason
from investigator.llm.gateway import ModelError, ModelRateLimited, ModelRejected, ModelUnavailable
from investigator.llm.messages import ChatRequest, ChatResponse, Message, Role, Usage
from investigator.llm.retry import Backoff, RetryingGateway

REQUEST = ChatRequest(purpose="test", messages=(Message(role=Role.USER, content="hi"),))
REPLY = ChatResponse(
    message=Message(role=Role.ASSISTANT, content="ok"),
    finish_reason=FinishReason.STOP,
    usage=Usage(prompt_tokens=1, completion_tokens=1),
    model="m",
    latency_ms=1,
)
STEADY = Backoff(attempts=3, first_delay_s=5, multiplier=3, jitter=0)


class FlakyGateway:
    def __init__(self, *errors: ModelError) -> None:
        self.errors = list(errors)
        self.calls = 0

    async def complete(self, request: ChatRequest) -> ChatResponse:
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return REPLY


class FakeTime:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        await asyncio.sleep(0)
        self.now += seconds


def retrying(inner: FlakyGateway, time: FakeTime) -> RetryingGateway:
    return RetryingGateway(inner, STEADY, clock=time.clock, sleep=time.sleep)


async def test_transient_failures_are_retried_with_growing_delays() -> None:
    inner, time = FlakyGateway(ModelRateLimited("429"), ModelUnavailable("502")), FakeTime()

    reply = await retrying(inner, time).complete(REQUEST)

    assert reply is REPLY
    assert inner.calls == 3
    assert time.sleeps == [5, 15]


async def test_retries_stop_at_the_limit_and_skip_permanent_errors() -> None:
    exhausted = FlakyGateway(*(ModelUnavailable("down") for _ in range(5)))
    rejected = FlakyGateway(ModelRejected("400"))

    with pytest.raises(ModelUnavailable):
        await retrying(exhausted, FakeTime()).complete(REQUEST)
    with pytest.raises(ModelRejected):
        await retrying(rejected, FakeTime()).complete(REQUEST)

    assert (exhausted.calls, rejected.calls) == (3, 1)


async def test_a_rate_limit_pauses_every_caller() -> None:
    inner, time = FlakyGateway(ModelRateLimited("429")), FakeTime()
    gateway = retrying(inner, time)

    await asyncio.gather(gateway.complete(REQUEST), gateway.complete(REQUEST))

    assert inner.calls == 3
    assert time.sleeps == [5, 5]


def test_jitter_keeps_delays_near_the_schedule() -> None:
    backoff = Backoff(first_delay_s=10, multiplier=2, max_delay_s=30, jitter=0.2)
    rng = Random(1)

    delays = [backoff.delay(retry, rng) for retry in (1, 2, 3, 4)]

    for delay, base in zip(delays, (10, 20, 30, 30), strict=True):
        assert 0.8 * base <= delay <= 1.2 * base
