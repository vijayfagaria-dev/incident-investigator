"""Rate limiting, credentials and structured-output parsing."""

from pathlib import Path

import pytest

from investigator.domain.base import DomainModel
from investigator.llm.gateway import StructuredOutputError
from investigator.llm.profiles import PROFILES, MissingCredentials, api_key
from investigator.llm.ratelimit import RateLimiter
from investigator.runtime.agent_loop import parse_structured


class FakeTime:
    def __init__(self) -> None:
        self.now = 0.0

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += seconds


async def test_rate_limiter_spaces_starts_to_the_per_minute_limit() -> None:
    time = FakeTime()
    limiter = RateLimiter(2, clock=time.clock, sleep=time.sleep)

    waits = [await limiter.acquire() for _ in range(3)]
    time.now += 61
    later = await limiter.acquire()

    assert waits == [0.0, 0.0, 60.0]
    assert later == 0.0


def test_api_key_prefers_the_environment_then_the_env_file(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("# keys\nNVIDIA_API_KEY='from-file'\n")
    profile = PROFILES["nvidia"]

    assert api_key(profile, environ={"NVIDIA_API_KEY": "from-env"}, env_file=env_file) == "from-env"
    assert api_key(profile, environ={}, env_file=env_file) == "from-file"
    assert api_key(PROFILES["ollama"], environ={}, env_file=env_file) == "not-needed"
    with pytest.raises(MissingCredentials, match="NVIDIA_API_KEY"):
        api_key(profile, environ={}, env_file=tmp_path / "missing.env")


class Answer(DomainModel):
    service: str
    confidence: float


def test_structured_replies_tolerate_fences_and_prose() -> None:
    reply = 'Here you go:\n```json\n{"service": "payments-service", "confidence": 0.8}\n```'
    assert parse_structured(reply, Answer) == Answer(service="payments-service", confidence=0.8)


@pytest.mark.parametrize(
    ("reply", "problem"),
    [
        ("I think it is payments.", "no JSON object"),
        ('{"service": "payments-service", "confidence": }', "not valid JSON"),
        ('{"service": "payments-service"}', "confidence: Field required"),
    ],
)
def test_unusable_replies_explain_what_is_wrong(reply: str, problem: str) -> None:
    with pytest.raises(StructuredOutputError, match=problem):
        parse_structured(reply, Answer)
