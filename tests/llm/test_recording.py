import asyncio
from pathlib import Path

import pytest

from investigator.llm.gateway import ModelRejected
from investigator.llm.messages import ChatRequest, Message, Role
from investigator.llm.recording import Cassette, RecordingGateway, ReplayGateway

from ..scripted import ScriptedGateway, say


def ask(purpose: str, text: str) -> ChatRequest:
    return ChatRequest(purpose=purpose, messages=(Message(role=Role.USER, content=text),))


class Ticks:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        self.now += 2.0
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        await asyncio.sleep(0)


async def test_a_recorded_run_replays_without_a_model(tmp_path: Path) -> None:
    cassette, ticks = Cassette(), Ticks()
    live = RecordingGateway(
        ScriptedGateway([say("first"), say("second")]), cassette, clock=ticks.clock
    )
    await live.complete(ask("critic", "a"))
    await live.complete(ask("critic", "b"))
    cassette.save(tmp_path / "run.jsonl.gz")

    replay = ReplayGateway(Cassette.load(tmp_path / "run.jsonl.gz"), speedup=4, sleep=ticks.sleep)
    second = await replay.complete(ask("critic", "b"))
    first = await replay.complete(ask("critic", "a"))

    assert (first.message.content, second.message.content) == ("first", "second")
    assert ticks.sleeps == [0.5, 0.5]
    assert replay.divergences == 0


async def test_an_unrecorded_request_gets_the_next_reply_for_its_role() -> None:
    cassette = Cassette()
    await RecordingGateway(ScriptedGateway([say("plan")]), cassette).complete(ask("plan", "x"))
    replay = ReplayGateway(cassette, sleep=Ticks().sleep)

    reply = await replay.complete(ask("plan", "something else"))

    assert reply.message.content == "plan"
    assert replay.divergences == 1
    with pytest.raises(ModelRejected):
        await replay.complete(ask("plan", "x"))
