"""Sweeps with a scripted model: what each run leaves behind, resuming, and replay."""

import asyncio
from pathlib import Path

from investigator.domain.report import Report
from investigator.eval.runner import (
    CASSETTE_FILE,
    RECORD_FILE,
    REPORT_FILE,
    TRACE_FILE,
    RunKey,
    RunRecord,
    Sweep,
    sweep_keys,
)
from investigator.investigation.config import InvestigationConfig
from investigator.llm.gateway import ModelGateway
from investigator.llm.messages import ChatRequest, ChatResponse
from investigator.llm.recording import Cassette, RecordingGateway, ReplayGateway
from investigator.systems import System, build_investigator
from investigator.tools.registry import build_tools
from investigator.tracing import MemoryTracer, Tracer
from investigator.world.dataset import Dataset

from ..baseline.test_solo import ANSWER, WINDOW
from ..investigation.test_run import two_round_script
from ..scripted import ScriptedGateway, answer, call, say

SOLO_D2 = RunKey("D2", System.SINGLE, 1)
DELAYS = {"observability": 0.03, "dependency": 0.01}


def solo_script() -> ScriptedGateway:
    return ScriptedGateway(
        [
            call(
                ("query_metrics", {"service": "payments-service", **WINDOW}),
                ("get_change_history", WINDOW),
            ),
            say("enough"),
            answer(ANSWER),
        ]
    )


def sweep(dataset: Dataset, out: Path, model: ModelGateway | None = None) -> Sweep:
    def gateways(_tracer: Tracer, cassette: Cassette) -> ModelGateway:
        return RecordingGateway(model or solo_script(), cassette)

    return Sweep(dataset, gateways, InvestigationConfig(), out, model="scripted")


def test_sweeps_go_trial_by_trial() -> None:
    keys = sweep_keys(["T01", "T02"], [System.MULTI, System.SINGLE], trials=2)

    assert [k.name for k in keys[:4]] == [
        "T01-multi-t1",
        "T01-single-t1",
        "T02-multi-t1",
        "T02-single-t1",
    ]
    assert {k.trial for k in keys[4:]} == {2}


async def test_each_run_leaves_its_report_trace_recording_and_record(
    dataset: Dataset, tmp_path: Path
) -> None:
    runner = sweep(dataset, tmp_path)

    [record] = await runner.run([SOLO_D2])

    directory = tmp_path / "D2-single-t1"
    assert {p.name for p in directory.iterdir()} >= {
        REPORT_FILE,
        TRACE_FILE,
        CASSETTE_FILE,
        RECORD_FILE,
    }
    assert record.error is None
    assert RunRecord.model_validate_json((directory / RECORD_FILE).read_text()) == record
    assert await runner.run([SOLO_D2]) == []


async def test_a_run_that_cannot_start_is_recorded_and_retried_next_time(
    dataset: Dataset, tmp_path: Path
) -> None:
    def no_endpoint(_tracer: Tracer, _cassette: Cassette) -> ModelGateway:
        raise RuntimeError("endpoint vanished")

    broken = Sweep(dataset, no_endpoint, InvestigationConfig(), tmp_path, model="scripted")

    [record] = await broken.run([SOLO_D2])

    assert record.error == "RuntimeError: endpoint vanished"
    assert not broken.is_done(SOLO_D2)
    [retried] = await sweep(dataset, tmp_path).run([SOLO_D2])
    assert retried.error is None


class Latency:
    """A scripted model that takes a while to answer, longer for some agents than others."""

    def __init__(self, inner: ModelGateway) -> None:
        self._inner = inner

    async def complete(self, request: ChatRequest) -> ChatResponse:
        await asyncio.sleep(DELAYS.get(request.purpose, 0.005))
        return await self._inner.complete(request)


async def replayed(dataset: Dataset, system: System, cassette: Cassette) -> tuple[Report, int]:
    tools = build_tools(dataset.telemetry("D2"), dataset.topology, dataset.history())
    gateway = ReplayGateway(cassette, speedup=3)
    investigator = build_investigator(system, gateway, tools, InvestigationConfig(), MemoryTracer())
    return await investigator.investigate(dataset.incident_report("D2")), gateway.divergences


async def test_a_recorded_team_run_replays_to_the_same_report(dataset: Dataset) -> None:
    cassette = Cassette()
    tools = build_tools(dataset.telemetry("D2"), dataset.topology, dataset.history())
    live = build_investigator(
        System.MULTI,
        RecordingGateway(Latency(ScriptedGateway(two_round_script())), cassette),
        tools,
        InvestigationConfig(),
        MemoryTracer(),
    )
    original = await live.investigate(dataset.incident_report("D2"))

    report, divergences = await replayed(dataset, System.MULTI, cassette)

    assert divergences == 0
    assert report.model_dump(exclude={"stats"}) == original.model_dump(exclude={"stats"})
