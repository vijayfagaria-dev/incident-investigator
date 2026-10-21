"""Running a sweep: every chosen incident, through every system, a few times over.

Each run leaves a directory with its report, trace, model recording and a record of how
it was run. A run whose record already exists is skipped, so an interrupted sweep resumes
where it stopped, and a failed run is retried on the next attempt.
"""

import asyncio
import hashlib
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path

from pydantic import AwareDatetime

from investigator.domain.base import DomainModel
from investigator.domain.report import Report
from investigator.investigation.config import InvestigationConfig
from investigator.llm.gateway import ModelGateway
from investigator.llm.recording import Cassette
from investigator.markdown import render_markdown
from investigator.systems import System, build_investigator
from investigator.tools.registry import incident_tools
from investigator.tracing import JsonlTracer, Tracer
from investigator.world.dataset import Dataset

REPORT_FILE = "report.json"
MARKDOWN_FILE = "report.md"
TRACE_FILE = "trace.jsonl"
CASSETTE_FILE = "cassette.jsonl.gz"
RECORD_FILE = "run.json"

GatewayFactory = Callable[[Tracer, Cassette], ModelGateway]
"""Builds the gateway for one run, tracing to that run's trace and recording its replies."""


@dataclass(frozen=True)
class RunKey:
    incident_id: str
    system: System
    trial: int

    @property
    def name(self) -> str:
        return f"{self.incident_id}-{self.system}-t{self.trial}"


class RunRecord(DomainModel):
    incident_id: str
    system: System
    trial: int
    model: str
    config_digest: str
    """Changes whenever the configuration or any prompt changes."""
    started_at: AwareDatetime
    wall_s: float
    error: str | None = None


def config_digest(config: InvestigationConfig) -> str:
    prompts = files("investigator.agents") / "prompts"
    texts = sorted(
        (entry.name, entry.read_text(encoding="utf-8"))
        for entry in prompts.iterdir()
        if entry.name.endswith(".md")
    )
    payload = config.model_dump_json() + "".join(name + text for name, text in texts)
    return hashlib.sha256(payload.encode()).hexdigest()[:12]


def sweep_keys(incident_ids: Sequence[str], systems: Sequence[System], trials: int) -> list[RunKey]:
    """Trial by trial, so a sweep cut short still covers every incident evenly."""
    return [
        RunKey(incident_id, system, trial)
        for trial in range(1, trials + 1)
        for incident_id in incident_ids
        for system in systems
    ]


class Sweep:
    def __init__(
        self,
        dataset: Dataset,
        gateways: GatewayFactory,
        config: InvestigationConfig,
        out: Path,
        *,
        model: str,
        concurrency: int = 2,
    ) -> None:
        self._dataset = dataset
        self._gateways = gateways
        self._config = config
        self._out = out
        self._model = model
        self._slots = asyncio.Semaphore(concurrency)

    def run_dir(self, key: RunKey) -> Path:
        return self._out / key.name

    def is_done(self, key: RunKey) -> bool:
        record = self.run_dir(key) / RECORD_FILE
        return record.exists() and RunRecord.model_validate_json(record.read_text()).error is None

    async def run(
        self, keys: Sequence[RunKey], on_done: Callable[[RunRecord], None] = lambda _: None
    ) -> list[RunRecord]:
        async def guarded(key: RunKey) -> RunRecord:
            async with self._slots:
                record = await self._run_one(key)
            on_done(record)
            return record

        return list(await asyncio.gather(*(guarded(k) for k in keys if not self.is_done(k))))

    async def _run_one(self, key: RunKey) -> RunRecord:
        directory = self.run_dir(key)
        directory.mkdir(parents=True, exist_ok=True)
        for stale in (TRACE_FILE, REPORT_FILE, MARKDOWN_FILE, CASSETTE_FILE):
            (directory / stale).unlink(missing_ok=True)
        tracer = JsonlTracer(directory / TRACE_FILE)
        cassette = Cassette()
        started_at, started = datetime.now(UTC), time.monotonic()
        error = None
        try:
            report = await self._investigate(key, tracer, cassette)
        except Exception as exc:  # One broken run must not end the sweep.
            error = f"{type(exc).__name__}: {exc}"
        else:
            (directory / REPORT_FILE).write_text(report.model_dump_json(indent=2))
            (directory / MARKDOWN_FILE).write_text(render_markdown(report))
        cassette.save(directory / CASSETTE_FILE)
        record = RunRecord(
            incident_id=key.incident_id,
            system=key.system,
            trial=key.trial,
            model=self._model,
            config_digest=config_digest(self._config),
            started_at=started_at,
            wall_s=round(time.monotonic() - started, 1),
            error=error,
        )
        (directory / RECORD_FILE).write_text(record.model_dump_json(indent=2))
        return record

    async def _investigate(self, key: RunKey, tracer: Tracer, cassette: Cassette) -> Report:
        dataset = self._dataset
        tools = incident_tools(dataset, key.incident_id)
        investigator = build_investigator(
            key.system, self._gateways(tracer, cassette), tools, self._config, tracer
        )
        return await investigator.investigate(dataset.incident_report(key.incident_id))
