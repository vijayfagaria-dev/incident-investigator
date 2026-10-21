"""The viewer's logic: finding recorded runs, replaying them and describing each step."""

from pathlib import Path

import pytest

from investigator.eval.runner import RunKey
from investigator.systems import System
from investigator.ui.replay import (
    Rerun,
    agent_states,
    board_at,
    describe,
    playback_schedule,
    recorded_runs,
    steps,
)
from investigator.world.dataset import Dataset

from ..eval.test_runner import SOLO_D2, sweep


@pytest.fixture
async def recorded(dataset: Dataset, tmp_path: Path) -> Path:
    await sweep(dataset, tmp_path).run([SOLO_D2])
    (tmp_path / "half-written").mkdir()
    return tmp_path


def test_only_finished_runs_are_offered(recorded: Path) -> None:
    runs = recorded_runs(recorded)

    assert [run.key for run in runs] == [RunKey("D2", System.SINGLE, 1)]
    assert runs[0].report.incident_id == "D2"


def test_a_replay_reruns_the_investigation_from_its_recording(
    recorded: Path, dataset: Dataset
) -> None:
    [run] = recorded_runs(recorded)

    replay = Rerun(run, dataset, speedup=1000).start()
    replay.wait(timeout_s=30)

    assert replay.error is None
    assert replay.matches_recording()
    assert (replay.replayed, replay.total, replay.divergences) == (3, 3, 0)
    assert any(event["event"] == "round_end" for event in replay.events)


def test_each_step_reads_as_what_an_agent_did(recorded: Path) -> None:
    [run] = recorded_runs(recorded)

    described = steps(run.trace)

    tools = [s.text for s in described if s.kind == "tool"]
    assert tools[0].startswith("query_metrics(payments-service, 09:00-10:20) → ok")
    [answer] = [s for s in described if s.kind == "commit"]
    assert answer.agent == "solo"
    assert answer.text == "proposed 2 hypotheses"
    assert any(d.startswith("refused: dropped observation") for d in answer.details)
    [round_closed] = [s for s in described if s.kind == "round"]
    assert "stopped: the agent finished its investigation" in round_closed.text


def test_agent_and_board_state_follow_the_events(recorded: Path) -> None:
    [run] = recorded_runs(recorded)
    first_tool = next(i for i, e in enumerate(run.trace) if e["event"] == "tool_call")

    working = agent_states(run.trace[:first_tool])["solo"]
    finished = agent_states(run.trace)["solo"]
    board = board_at(run.trace)

    assert (working.status, finished.status, finished.tasks) == ("working", "done", 1)
    assert finished.tool_calls == 2
    assert (board.observations, board.refused, board.round) == (3, 1, 1)
    assert board.standings[0]["hypothesis_id"] == "HYP-1"


def test_bookkeeping_events_are_not_shown() -> None:
    assert describe({"event": "tool_attempt", "attempt": 1}) is None
    assert describe({"event": "model_call", "purpose": "critic", "error": None}) is None


def test_playback_keeps_the_order_and_caps_long_pauses() -> None:
    events: list[dict[str, object]] = [
        {"event": "task_start", "task_id": "a", "label": "critic", "attempt": 1,
         "at": "2026-10-20T10:00:00+00:00"},
        {"event": "tool_attempt", "at": "2026-10-20T10:00:01+00:00"},
        {"event": "task_finish", "task_id": "a", "label": "critic", "state": "succeeded",
         "at": "2026-10-20T10:00:03+00:00"},
        {"event": "task_start", "task_id": "b", "label": "critic", "attempt": 1,
         "at": "2026-10-20T10:10:00+00:00"},
    ]  # fmt: skip

    schedule = playback_schedule(events, speed=2)

    assert [index for _, index in schedule] == [0, 2, 3]
    assert [due for due, _ in schedule] == [0.0, 1.5, 3.0]


def test_a_switch_to_the_backup_model_is_shown() -> None:
    step = describe(
        {
            "event": "model_fallback",
            "purpose": "critic",
            "failed_model": "nvidia/nemotron-3-ultra-550b-a55b",
            "backup_model": "z-ai/glm-5.3",
            "error": "ModelRateLimited: 429",
        }
    )

    assert step is not None
    assert (step.agent, step.kind) == ("critic", "model")
    assert step.text == "the main model kept failing, so the request went to z-ai/glm-5.3"
    assert step.details == ("ModelRateLimited: 429",)
