"""Command-line entry point."""

import asyncio
import importlib.util
import json
import subprocess
import sys
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Annotated

import typer

from investigator import __version__
from investigator.domain.telemetry import LogLevel
from investigator.eval.ground_truth import Split, load_ground_truth
from investigator.eval.runner import (
    RunKey,
    RunRecord,
    Sweep,
    sweep_keys,
)
from investigator.eval.summary import (
    load_results,
    render_summary,
    write_scores,
)
from investigator.investigation.config import InvestigationConfig
from investigator.llm.fallback import FallbackGateway
from investigator.llm.gateway import ModelGateway
from investigator.llm.openai_compat import OpenAICompatGateway
from investigator.llm.profiles import PROFILES, MissingCredentials, ProviderProfile, api_key
from investigator.llm.ratelimit import RateLimiter
from investigator.llm.recording import Cassette, RecordingGateway, ReplayGateway
from investigator.llm.retry import Cooldown, RetryingGateway
from investigator.markdown import render_markdown
from investigator.systems import System, build_investigator
from investigator.tools.executor import ToolExecutor
from investigator.tools.registry import incident_tools
from investigator.tracing import JsonlTracer, MemoryTracer, Tracer
from investigator.world.dataset import Dataset, DatasetError
from investigator.world.export import export_world

app = typer.Typer(no_args_is_help=True)
eval_app = typer.Typer(no_args_is_help=True, help="Compare the agent team with the baseline.")
app.add_typer(eval_app, name="eval")
data_app = typer.Typer(no_args_is_help=True, help="Inspect the synthetic incident dataset.")
app.add_typer(data_app, name="data")
tools_app = typer.Typer(no_args_is_help=True, help="Call investigation tools directly.")
app.add_typer(tools_app, name="tools")

DatasetOption = Annotated[
    Path,
    typer.Option("--datasets", envvar="INVESTIGATOR_DATASETS", help="Dataset directory."),
]


def _print_version(value: bool) -> None:
    if value:
        typer.echo(f"investigator {__version__}")
        raise typer.Exit


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_print_version,
            is_eager=True,
            help="Show the version and exit.",
        ),
    ] = False,
) -> None:
    """Investigate production incidents with a team of cooperating agents."""


@data_app.command("list")
def list_incidents(datasets: DatasetOption = Path("datasets")) -> None:
    """List the incidents in the dataset."""
    dataset = Dataset(datasets)
    try:
        for incident_id in dataset.incident_ids():
            report = dataset.incident_report(incident_id)
            typer.echo(f"{incident_id:<5} {report.severity:<5} {report.title}")
    except DatasetError as exc:
        raise typer.BadParameter(str(exc)) from exc


@data_app.command("render")
def render_incident(
    incident_id: str,
    out: Annotated[
        Path | None, typer.Option(help="Also write the telemetry to this directory.")
    ] = None,
    datasets: DatasetOption = Path("datasets"),
) -> None:
    """Render an incident's telemetry and summarise it."""
    dataset = Dataset(datasets)
    try:
        report = dataset.incident_report(incident_id)
        store = dataset.telemetry(incident_id)
    except DatasetError as exc:
        raise typer.BadParameter(str(exc)) from exc

    levels = Counter(record.level for record in store.logs)
    minutes = len(store.window.minutes())
    typer.echo(f"{report.id}: {report.title}")
    typer.echo(f"  window   {store.window.start:%Y-%m-%d %H:%M} to {store.window.end:%H:%M} UTC")
    typer.echo(
        f"  logs     {len(store.logs):,} lines "
        f"({levels[LogLevel.WARN]:,} WARN, {levels[LogLevel.ERROR]:,} ERROR)"
    )
    typer.echo(f"  metrics  {len(store.metrics)} series x {minutes} minutes")
    typer.echo(f"  changes  {len(store.changes)}")
    if out is not None:
        for path in export_world(report, store, out):
            typer.echo(f"  wrote    {path}")


@tools_app.command("call")
def call_tool(
    tool: str,
    incident: Annotated[str, typer.Option(help="Incident whose telemetry to query.")],
    args: Annotated[str, typer.Option(help="Tool arguments as a JSON object.")] = "{}",
    datasets: DatasetOption = Path("datasets"),
) -> None:
    """Call one tool against an incident, with its backend faults, and print the result."""
    dataset = Dataset(datasets)
    try:
        arguments = json.loads(args)
        registry = incident_tools(dataset, incident)
    except (DatasetError, json.JSONDecodeError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    if not isinstance(arguments, dict):
        raise typer.BadParameter("--args must be a JSON object")
    result = asyncio.run(ToolExecutor(registry).execute(tool, arguments))
    typer.echo(result.model_dump_json(indent=2))


@app.command()
def investigate(
    incident_id: str,
    system: Annotated[
        System, typer.Option(help="The agent team, or the single-agent baseline.")
    ] = System.MULTI,
    profile: Annotated[
        str, typer.Option(help=f"Model endpoint: {', '.join(PROFILES)}.")
    ] = "nvidia",
    rounds: Annotated[int, typer.Option(min=1, help="Most investigation rounds to run.")] = 2,
    trace: Annotated[Path | None, typer.Option(help="Write a JSONL trace here.")] = None,
    out: Annotated[Path | None, typer.Option(help="Also write the Markdown report here.")] = None,
    json_out: Annotated[
        Path | None, typer.Option("--json", help="Also write the report as JSON here.")
    ] = None,
    replay: Annotated[
        Path | None,
        typer.Option(help="Replay a recorded cassette instead of calling a model; no key needed."),
    ] = None,
    datasets: DatasetOption = Path("datasets"),
) -> None:
    """Investigate an incident and print the report."""
    _check_profile(profile)
    dataset = Dataset(datasets)
    tracer: Tracer = JsonlTracer(trace) if trace else MemoryTracer()
    replayer = ReplayGateway(Cassette.load(replay)) if replay is not None else None
    try:
        incident = dataset.incident_report(incident_id)
        tools = incident_tools(dataset, incident_id)
        gateway = replayer if replayer is not None else _live_models(profile)(tracer)
    except (DatasetError, MissingCredentials) as exc:
        raise typer.BadParameter(str(exc)) from exc

    investigator = build_investigator(
        system, gateway, tools, InvestigationConfig(max_rounds=rounds), tracer
    )
    report = asyncio.run(investigator.investigate(incident))
    if replayer is not None and replayer.divergences:
        typer.echo(f"note: {replayer.divergences} requests differed from the recording", err=True)
    markdown = render_markdown(report)
    typer.echo(markdown)
    if out is not None:
        _write(out, markdown)
    if json_out is not None:
        _write(json_out, report.model_dump_json(indent=2))


@eval_app.command("run")
def eval_run(
    out: Annotated[Path, typer.Option(help="Directory for this sweep's runs.")],
    split: Annotated[Split, typer.Option(help="Which incidents to run.")] = Split.TEST,
    incidents: Annotated[
        list[str] | None, typer.Option("--incident", help="Only this incident; repeatable.")
    ] = None,
    systems: Annotated[
        list[System] | None, typer.Option("--system", help="Only this system; repeatable.")
    ] = None,
    trials: Annotated[int, typer.Option(min=1, help="Runs per incident and system.")] = 3,
    concurrency: Annotated[int, typer.Option(min=1, help="Runs in flight at once.")] = 2,
    profile: Annotated[
        str, typer.Option(help=f"Model endpoint: {', '.join(PROFILES)}.")
    ] = "nvidia",
    rounds: Annotated[int, typer.Option(min=1, help="Most investigation rounds to run.")] = 2,
    datasets: DatasetOption = Path("datasets"),
) -> None:
    """Run every chosen incident through each system, resuming where a sweep stopped."""
    _check_profile(profile)
    dataset = Dataset(datasets)
    try:
        models = _live_models(profile)
        chosen = incidents or [
            i for i in dataset.incident_ids() if load_ground_truth(dataset, i).split is split
        ]
    except (DatasetError, MissingCredentials) as exc:
        raise typer.BadParameter(str(exc)) from exc

    def make_gateway(tracer: Tracer, cassette: Cassette) -> ModelGateway:
        return RecordingGateway(models(tracer), cassette)

    sweep = Sweep(
        dataset,
        make_gateway,
        InvestigationConfig(max_rounds=rounds),
        out,
        model=PROFILES[profile].model,
        concurrency=concurrency,
    )
    keys = sweep_keys(chosen, systems or list(System), trials)
    pending = [k for k in keys if not sweep.is_done(k)]
    typer.echo(f"{len(pending)} of {len(keys)} runs to go", err=True)

    def print_progress(record: RunRecord) -> None:
        name = RunKey(record.incident_id, record.system, record.trial).name
        status = f"failed: {record.error}" if record.error else "done"
        typer.echo(f"{name} {status} in {record.wall_s:.0f}s", err=True)

    records = asyncio.run(sweep.run(pending, on_done=print_progress))
    if failed := [r for r in records if r.error]:
        typer.echo(f"{len(failed)} runs failed; run the same command again to retry them", err=True)
        raise typer.Exit(1)


@eval_app.command("report")
def eval_report(
    sweep: Annotated[Path, typer.Argument(help="A directory written by 'eval run'.")],
    title: Annotated[str, typer.Option(help="Heading for the summary.")] = "Evaluation results",
    datasets: DatasetOption = Path("datasets"),
) -> None:
    """Score a sweep's runs and write scores.json and summary.md next to them."""
    if not sweep.is_dir():
        raise typer.BadParameter(f"{sweep} is not a directory")
    results = load_results(sweep, Dataset(datasets))
    write_scores(results, sweep / "scores.json")
    summary = render_summary(results, title)
    (sweep / "summary.md").write_text(summary, encoding="utf-8")
    typer.echo(summary)


@app.command()
def ui(
    results: Annotated[Path, typer.Option(help="A sweep directory to show.")] = Path(
        "results/test"
    ),
    datasets: DatasetOption = Path("datasets"),
) -> None:
    """Open the investigation viewer in a browser: replay recorded runs, no key needed."""
    if importlib.util.find_spec("streamlit") is None:
        typer.echo("The viewer needs the ui extra: uv sync --extra ui", err=True)
        raise typer.Exit(1)
    page = Path(__file__).parent / "ui" / "app.py"
    command = [
        sys.executable, "-m", "streamlit", "run", str(page),
        "--browser.gatherUsageStats", "false",
        "--client.toolbarMode", "viewer",
        "--theme.base", "dark",
        "--theme.primaryColor", "#6aa5ff",
        "--theme.backgroundColor", "#070a12",
        "--theme.secondaryBackgroundColor", "#121a2c",
        "--theme.textColor", "#e6ebf5",
        "--", "--results", str(results), "--datasets", str(datasets),
    ]  # fmt: skip
    raise typer.Exit(subprocess.call(command))


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _check_profile(profile: str) -> None:
    if profile not in PROFILES:
        raise typer.BadParameter(f"unknown profile {profile!r}; choose from {', '.join(PROFILES)}")


def _live_models(profile: str) -> Callable[[Tracer], ModelGateway]:
    """Makes gateways to the profile's model, with retries, and its backup if it has one.

    The keys are checked here, before any run starts. Every gateway made shares one rate
    limit and one cooldown, so parallel runs and the backup stay within one free allowance.
    """
    main = PROFILES[profile]
    backup = PROFILES[main.fallback] if main.fallback else None
    keys = {p.name: api_key(p) for p in (main, backup) if p is not None}
    limiter, cooldown = RateLimiter(main.requests_per_minute), Cooldown()

    def connect(endpoint: ProviderProfile, tracer: Tracer) -> ModelGateway:
        client = OpenAICompatGateway.connect(
            endpoint, keys[endpoint.name], limiter=limiter, tracer=tracer
        )
        return RetryingGateway(client, cooldown=cooldown)

    def gateway(tracer: Tracer) -> ModelGateway:
        if backup is None:
            return connect(main, tracer)
        return FallbackGateway(
            connect(main, tracer),
            connect(backup, tracer),
            main_model=main.model,
            backup_model=backup.model,
            tracer=tracer,
        )

    return gateway
