"""Recorded investigations: finding them, playing them back, re-running them, and saying
what each step did.

Nothing here calls a model. A playback shows the recorded trace at its own pace; a re-run
answers every model request from the run's recording. The Streamlit page only draws what
this module works out, so all of it can be tested without a browser.
"""

import asyncio
import json
import threading
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from functools import cached_property
from pathlib import Path
from typing import Any

from investigator.domain.report import Report
from investigator.eval.runner import (
    CASSETTE_FILE,
    RECORD_FILE,
    REPORT_FILE,
    TRACE_FILE,
    RunKey,
    RunRecord,
)
from investigator.investigation.config import InvestigationConfig
from investigator.llm.recording import Cassette, ReplayGateway
from investigator.systems import System, build_investigator
from investigator.tools.registry import incident_tools
from investigator.tracing import TraceEvent
from investigator.world.dataset import Dataset

AGENTS = ("orchestrator", "observability", "dependency", "reasoning", "critic", "reporting", "solo")
"""Every agent role, in the order an investigation uses them."""

Event = Mapping[str, Any]


@dataclass(frozen=True)
class RecordedRun:
    """One finished run of a sweep, with everything needed to show or replay it."""

    directory: Path
    record: RunRecord

    @property
    def key(self) -> RunKey:
        return RunKey(self.record.incident_id, System(self.record.system), self.record.trial)

    @cached_property
    def report(self) -> Report:
        return Report.model_validate_json((self.directory / REPORT_FILE).read_text())

    @cached_property
    def trace(self) -> list[dict[str, Any]]:
        lines = (self.directory / TRACE_FILE).read_text().splitlines()
        return [json.loads(line) for line in lines if line.strip()]

    def cassette(self) -> Cassette:
        return Cassette.load(self.directory / CASSETTE_FILE)


def recorded_runs(sweep: Path) -> list[RecordedRun]:
    """Every run in a sweep that finished and can be replayed, in a stable order."""
    runs = []
    for directory in sorted(sweep.iterdir()) if sweep.is_dir() else ():
        files = [directory / name for name in (RECORD_FILE, REPORT_FILE, CASSETTE_FILE)]
        if not all(path.exists() for path in files):
            continue
        record = RunRecord.model_validate_json((directory / RECORD_FILE).read_text())
        if record.error is None:
            runs.append(RecordedRun(directory, record))
    return runs


class _ListTracer:
    """Keeps every event as plain JSON, so another thread can read them as they arrive."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def record(self, event: TraceEvent) -> None:
        self.events.append(event.model_dump(mode="json"))


class Rerun:
    """A recorded investigation run again through the real code, in a background thread.

    Every model request is answered from the recording; the tools, the board and every rule
    run for real. Replies come back faster than they did live, so concurrent agents can
    finish in another order, and a step that timed out live may not time out again; either
    makes the re-run diverge, which ``matches_recording`` reports.
    """

    def __init__(self, run: RecordedRun, dataset: Dataset, speedup: float) -> None:
        cassette = run.cassette()
        self.total = len(cassette.recordings)
        self.report: Report | None = None
        self.error: str | None = None
        self._run = run
        self._dataset = dataset
        self._tracer = _ListTracer()
        self._gateway = ReplayGateway(cassette, speedup=speedup)
        self._thread = threading.Thread(target=self._investigate, daemon=True)

    @property
    def events(self) -> list[dict[str, Any]]:
        return self._tracer.events

    @property
    def replayed(self) -> int:
        """Recorded replies used so far."""
        return self.total - self._gateway.remaining

    @property
    def divergences(self) -> int:
        return self._gateway.divergences

    @property
    def done(self) -> bool:
        return not self._thread.is_alive() and (self.report is not None or self.error is not None)

    def start(self) -> "Rerun":
        self._thread.start()
        return self

    def wait(self, timeout_s: float | None = None) -> None:
        self._thread.join(timeout_s)

    def matches_recording(self) -> bool:
        """Whether the re-run reached the same report as the recorded one."""
        if self.report is None:
            return False
        return _comparable(self.report) == _comparable(self._run.report)

    def _investigate(self) -> None:
        record = self._run.record
        try:
            investigator = build_investigator(
                System(record.system),
                self._gateway,
                incident_tools(self._dataset, record.incident_id),
                InvestigationConfig(),
                self._tracer,
            )
            incident = self._dataset.incident_report(record.incident_id)
            self.report = asyncio.run(investigator.investigate(incident))
        except Exception as exc:  # Shown on the page instead of killing the thread silently.
            self.error = f"{type(exc).__name__}: {exc}"


def _comparable(report: Report) -> dict[str, Any]:
    data = report.model_dump(mode="json")
    data["stats"].pop("elapsed_s")
    return data


@dataclass(frozen=True)
class Step:
    """One thing that happened, in words."""

    agent: str
    kind: str
    """task, tool, commit, round or model."""
    text: str
    details: tuple[str, ...] = ()
    failed: bool = False


def describe(event: Event) -> Step | None:
    """What an event means to someone watching, or None for bookkeeping not worth showing."""
    kind = event.get("event")
    if kind == "task_start":
        attempt = event.get("attempt", 1)
        retry = f" (attempt {attempt})" if attempt > 1 else ""
        return Step(_lane(event.get("label")), "task", f"started {event['task_id']}{retry}")
    if kind == "task_finish":
        if event.get("state") == "succeeded":
            return Step(_lane(event.get("label")), "task", f"finished {event['task_id']}")
        reason = event.get("error") or event.get("state")
        return Step(
            _lane(event.get("label")), "task", f"{event['task_id']} failed: {reason}", failed=True
        )
    if kind == "tool_call":
        return _tool_step(event)
    if kind == "agent_commit":
        return _commit_step(event)
    if kind == "round_end":
        return _round_step(event)
    if kind == "model_fallback":
        return Step(
            _lane(event.get("purpose")),
            "model",
            f"the main model kept failing, so the request went to {event['backup_model']}",
            details=(str(event.get("error", ""))[:160],),
        )
    if kind == "model_call" and event.get("error"):
        return Step(
            _lane(event.get("purpose")), "model", f"model call retried: {event['error']}"[:160]
        )
    return None


def steps(events: Iterable[Event]) -> list[Step]:
    return [step for event in events if (step := describe(event)) is not None]


def playback_schedule(
    events: Sequence[Event], speed: float, max_pause_s: float = 1.5
) -> list[tuple[float, int]]:
    """When to show each step of a recorded run: seconds from the start, and the event index.

    Gaps between events keep their real proportions at ``speed`` times real time, but no
    single pause lasts longer than ``max_pause_s``, so long waits such as rate limits do not
    stall the playback.
    """
    schedule = []
    clock = 0.0
    previous: datetime | None = None
    for index, event in enumerate(events):
        if describe(event) is None:
            continue
        at = datetime.fromisoformat(str(event["at"]))
        if previous is not None:
            clock += min(max_pause_s, (at - previous).total_seconds() / speed)
        previous = at
        schedule.append((clock, index))
    return schedule


@dataclass
class AgentState:
    status: str = "waiting"
    """waiting, working, done or failed."""
    tasks: int = 0
    tool_calls: int = 0
    current: str = ""


def agent_states(events: Iterable[Event]) -> dict[str, AgentState]:
    """Each agent's state after these events: what it is doing and how much it has done."""
    states = {agent: AgentState() for agent in AGENTS}
    running: dict[str, set[str]] = {agent: set() for agent in AGENTS}
    for event in events:
        kind = event.get("event")
        if kind == "task_start":
            agent = _lane(event.get("label"))
            running[agent].add(event["task_id"])
            states[agent].status = "working"
            states[agent].current = event["task_id"]
        elif kind == "task_finish":
            agent = _lane(event.get("label"))
            running[agent].discard(event["task_id"])
            states[agent].tasks += 1
            if event.get("state") != "succeeded":
                states[agent].status = "failed"
            elif not running[agent]:
                states[agent].status = "done"
        elif kind == "tool_call":
            states[_lane(event.get("caller"))].tool_calls += 1
    return states


@dataclass(frozen=True)
class BoardSnapshot:
    """What the shared board held after some number of events."""

    observations: int = 0
    refused: int = 0
    round: int = 0
    standings: tuple[Mapping[str, Any], ...] = ()
    verdicts: tuple[str, ...] = ()
    objections: tuple[str, ...] = ()
    requests: tuple[str, ...] = ()


def board_at(events: Sequence[Event]) -> BoardSnapshot:
    observations = refused = round_no = 0
    standings: tuple[Mapping[str, Any], ...] = ()
    verdicts: tuple[str, ...] = ()
    objections: tuple[str, ...] = ()
    requests: tuple[str, ...] = ()
    for event in events:
        kind = event.get("event")
        if kind == "agent_commit":
            observations += sum(str(i).startswith("OBS-") for i in event.get("accepted", ()))
            refused += sum(_is_refusal(problem) for problem in event.get("problems", ()))
            if event.get("role") == "critic":
                output = event.get("output") or {}
                verdicts = tuple(
                    f"{v['hypothesis_id']}: {v['verdict']}" for v in output.get("verdicts", ())
                )
                objections = tuple(_objection(o) for o in output.get("objections", ()))
                requests = tuple(r["question"] for r in output.get("requests", ()))
        elif kind == "round_end":
            round_no = event.get("round", round_no)
            standings = tuple(event.get("standings", ()))
    return BoardSnapshot(observations, refused, round_no, standings, verdicts, objections, requests)


def cause(standing: Mapping[str, Any]) -> str:
    trigger = f" ({standing['trigger']})" if standing.get("trigger") else ""
    return f"{standing['category']} on {standing['service']}{trigger}"


def _tool_step(event: Event) -> Step:
    arguments = event.get("arguments") or {}
    shown = [str(arguments[k]) for k in ("service", "metric", "contains") if arguments.get(k)]
    if arguments.get("start") and arguments.get("end"):
        shown.append(f"{str(arguments['start'])[11:16]}-{str(arguments['end'])[11:16]}")
    status = "cached" if event.get("cached") else event.get("status", "")
    attempts = event.get("attempts", 1)
    retried = f", {attempts} attempts" if attempts > 1 else ""
    returned = len(event.get("artifacts", ()))
    text = f"{event.get('tool')}({', '.join(shown)}) → {status}{retried}, {returned} ids"
    return Step(_lane(event.get("caller")), "tool", text, failed=status == "error")


def _commit_step(event: Event) -> Step:
    role = _lane(event.get("role"))
    output = event.get("output") or {}
    refused = tuple(f"refused: {p}" for p in event.get("problems", ()) if _is_refusal(p))
    if event.get("error"):
        return Step(role, "commit", f"its result could not be used: {event['error']}", failed=True)
    if role == "orchestrator":
        tasks = output.get("tasks", ())
        details = tuple(f"→ {t['agent']}: {t['focus']}" for t in tasks)
        dropped = tuple(f"dropped: {d}" for d in output.get("dropped", ()))
        return Step(role, "commit", f"assigned {len(tasks)} tasks", (*details, *dropped))
    if role in ("observability", "dependency"):
        found = output.get("observations", ())
        details = tuple(o["statement"] for o in found[:4])
        text = (
            f"posted {len(found)} observations, {len(output.get('leads', ()))} leads, "
            f"{len(output.get('gaps', ()))} gaps"
        )
        return Step(role, "commit", text, (*details, *refused))
    if role in ("reasoning", "solo"):
        hypotheses = output.get("hypotheses", ())
        details = tuple(
            f"{h['root_cause']['category']} on {h['root_cause']['service']} ({h['confidence']:.0%})"
            for h in hypotheses
        )
        asked = tuple(f"asked: {r['question']}" for r in output.get("requests", ()))
        return Step(
            role, "commit", f"proposed {len(hypotheses)} hypotheses", (*details, *asked, *refused)
        )
    if role == "critic":
        verdicts = tuple(
            f"{v['hypothesis_id']}: {v['verdict']}" for v in output.get("verdicts", ())
        )
        objections = tuple(_objection(o) for o in output.get("objections", ()))
        asked = tuple(f"asked: {r['question']}" for r in output.get("requests", ()))
        return Step(
            role, "commit", f"reviewed {len(verdicts)} hypotheses", (*verdicts, *objections, *asked)
        )
    return Step(role, "commit", "wrote the report")


def _round_step(event: Event) -> Step:
    details = tuple(
        f"{s['hypothesis_id']} {cause(s)}: {s['confidence']:.0%}"
        + (f", critic: {s['verdict']}" if s.get("verdict") else "")
        for s in event.get("standings", ())
    )
    reason = event.get("stop_reason")
    ending = f"; stopped: {reason}" if reason else "; continuing"
    return Step("orchestrator", "round", f"round {event.get('round')} closed{ending}", details)


def _objection(objection: Mapping[str, Any]) -> str:
    return (
        f"[{objection['severity']}] {objection['hypothesis_id']} "
        f"{objection['kind']}: {objection['detail']}"
    )


def _is_refusal(problem: str) -> bool:
    return problem.startswith(("dropped observation citing nothing", "removed citations"))


def _lane(role: object) -> str:
    """The agent lane an event belongs to; planning and the census run as the orchestrator."""
    name = str(role or "orchestrator")
    return name if name in AGENTS else "orchestrator"
