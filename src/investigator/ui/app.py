"""The investigation viewer: replay a recorded investigation and watch the agents work.

Start it with ``investigator ui``. It only reads recorded runs, so no model is called and
no key is needed.
"""

import itertools
import os
import sys
import time
from collections.abc import Mapping
from html import escape
from pathlib import Path

import streamlit as st

from investigator.domain.causes import Outcome
from investigator.domain.investigation import Assumption, Observation
from investigator.domain.report import RankedHypothesis, Report
from investigator.eval.scoring import RunScore
from investigator.eval.summary import SYSTEM_NAMES, SweepResults, load_results, overall_rows
from investigator.systems import System
from investigator.ui import style
from investigator.ui.replay import (
    AGENTS,
    AgentState,
    BoardSnapshot,
    RecordedRun,
    Rerun,
    Step,
    agent_states,
    board_at,
    cause,
    describe,
    playback_schedule,
    recorded_runs,
)
from investigator.world.dataset import Dataset

SPEEDS = {"10x": 10.0, "30x": 30.0, "100x": 100.0, "Instant": 1e6}
REFRESH_S = 0.25


def main() -> None:
    st.set_page_config(page_title="Incident investigator", layout="wide")
    st.markdown(style.CSS, unsafe_allow_html=True)
    results_dir, datasets_dir = _paths(sys.argv[1:])
    runs = _recorded_runs(str(results_dir))
    if not runs:
        st.warning(f"No recorded runs in {results_dir}. Run `investigator eval run` first.")
        return
    dataset = _dataset(str(datasets_dir))
    run, speed = _sidebar(runs, dataset)
    _incident_card(run, dataset)
    replay_tab, report_tab, compare_tab, score_tab = st.tabs(
        ["Replay", "Report", "Team vs baseline", "Scoreboard"]
    )
    with replay_tab:
        _replay_tab(run, dataset, speed)
    with report_tab:
        _report_tab(run.report)
    results = _results(str(results_dir), str(datasets_dir))
    with compare_tab:
        _compare_tab(results, run)
    with score_tab:
        _scoreboard(results)


def _paths(arguments: list[str]) -> tuple[Path, Path]:
    """Folders from the command line, or the environment, or the repository's defaults."""
    options = {
        "--results": os.environ.get("INVESTIGATOR_RESULTS", "results/test"),
        "--datasets": os.environ.get("INVESTIGATOR_DATASETS", "datasets"),
    }
    for name, value in itertools.pairwise(arguments):
        if name in options:
            options[name] = value
    return Path(options["--results"]), Path(options["--datasets"])


@st.cache_resource(ttl=30)
def _recorded_runs(results_dir: str) -> list[RecordedRun]:
    return recorded_runs(Path(results_dir))


@st.cache_resource
def _dataset(datasets_dir: str) -> Dataset:
    return Dataset(Path(datasets_dir))


@st.cache_resource(ttl=30)
def _results(results_dir: str, datasets_dir: str) -> SweepResults:
    return load_results(Path(results_dir), _dataset(datasets_dir))


# --- Sidebar and incident ----------------------------------------------------------------


def _sidebar(runs: list[RecordedRun], dataset: Dataset) -> tuple[RecordedRun, float]:
    with st.sidebar:
        st.markdown("### Incident investigator")
        st.caption("Replays recorded investigations. No model is called and no key is needed.")
        incidents = sorted({r.record.incident_id for r in runs})
        incident = st.selectbox(
            "Incident",
            incidents,
            format_func=lambda i: f"{i} · {dataset.incident_report(i).title}",
        )
        systems = [s for s in System if any(_matches(r, incident, s) for r in runs)]
        system = st.radio("System", systems, format_func=lambda s: SYSTEM_NAMES[s], horizontal=True)
        trials = sorted(r.record.trial for r in runs if _matches(r, incident, system))
        trial = st.selectbox("Trial", trials, format_func=lambda t: f"Trial {t}")
        speed = st.select_slider("Replay speed", options=list(SPEEDS), value="30x")
        st.divider()
        st.caption(
            "A replay runs the real investigation code again, answering every model request "
            "from the run's recording. The tools, the board and every rule run for real."
        )
    run = next(r for r in runs if _matches(r, incident, system) and r.record.trial == trial)
    return run, SPEEDS[speed]


def _matches(run: RecordedRun, incident: str, system: System) -> bool:
    return run.record.incident_id == incident and run.record.system == system


def _incident_card(run: RecordedRun, dataset: Dataset) -> None:
    incident = dataset.incident_report(run.record.incident_id)
    report = run.report
    outcome_kind = "ok" if report.outcome is Outcome.CONCLUSIVE else "warn"
    symptoms = "".join(style.chip(s) for s in incident.symptoms)
    notes = style.bullet_list(incident.responder_notes)
    st.markdown(
        f"""<div class="glass-card">
<div class="eyebrow">Incident {escape(incident.id)} · {escape(incident.severity)} · reported
{incident.reported_at:%Y-%m-%d %H:%M} UTC by {escape(incident.reported_by)}</div>
<div class="incident-title">{escape(incident.title)}</div>
<div>{escape(incident.summary)}</div>
<div style="margin-top:10px">{symptoms}</div>
<div class="dim" style="margin-top:8px">Responder notes (unverified):</div>{notes}
<div style="margin-top:10px">{style.chip(f"recorded outcome: {report.outcome}", outcome_kind)}
{style.chip(_cause_text(report), "info") if report.root_cause else ""}</div>
</div>""",
        unsafe_allow_html=True,
    )


# --- Replay ------------------------------------------------------------------------------


def _replay_tab(run: RecordedRun, dataset: Dataset, speed: float) -> None:
    key = run.directory.name
    rerun: Rerun | None = st.session_state.get("rerun")
    if rerun is not None and st.session_state.get("rerun_of") != key:
        rerun = None
    intro, play, again = st.columns([4, 1, 1])
    intro.markdown(
        "**Replay** plays back what the agents did in this run, at its real pace sped up. "
        "**Re-run** runs the investigation code again, answering each model request from the "
        "recording. Afterwards, the slider steps through every event."
    )
    if play.button("▶ Replay", type="primary", use_container_width=True):
        _play_back(run.trace, run.record.system, speed)
    if again.button("↻ Re-run", use_container_width=True):
        rerun = Rerun(run, dataset, speed).start()
        st.session_state["rerun"], st.session_state["rerun_of"] = rerun, key
        _watch(rerun, run)
    source = "Recorded run"
    if rerun is not None and rerun.done:
        _rerun_verdict(rerun)
        source = st.radio(
            "Show", ["Recorded run", "The re-run"], horizontal=True, label_visibility="collapsed"
        )
    events = rerun.events if rerun is not None and source == "The re-run" else run.trace
    _step_through(events, run.record.system)


def _play_back(events: list[dict[str, object]], system: str, speed: float) -> None:
    schedule = playback_schedule(events, speed)
    progress = st.progress(0.0, text="Starting the replay")
    lanes = st.empty()
    feed = st.empty()
    started = time.monotonic()
    drawn_at = -REFRESH_S
    for position, (due, index) in enumerate(schedule, start=1):
        pause = due - (time.monotonic() - started)
        if pause > 0:
            time.sleep(pause)
        last = position == len(schedule)
        if time.monotonic() - drawn_at < REFRESH_S and not last:
            continue
        drawn_at = time.monotonic()
        shown = events[: index + 1]
        progress.progress(position / len(schedule), text=f"Step {position} of {len(schedule)}")
        lanes.markdown(_lanes_html(agent_states(shown), system), unsafe_allow_html=True)
        recent = [s for e in shown if (s := describe(e)) is not None][-8:]
        feed.markdown("".join(_step_html(s) for s in reversed(recent)), unsafe_allow_html=True)
    feed.empty()


def _watch(rerun: Rerun, run: RecordedRun) -> None:
    progress = st.progress(0.0, text="Starting the re-run")
    lanes = st.empty()
    feed = st.empty()
    while True:
        finished = rerun.done
        events = list(rerun.events)
        fraction = rerun.replayed / rerun.total if rerun.total else 1.0
        progress.progress(
            min(1.0, fraction), text=f"{rerun.replayed} of {rerun.total} recorded replies used"
        )
        lanes.markdown(_lanes_html(agent_states(events), run.record.system), unsafe_allow_html=True)
        recent = [s for e in events if (s := describe(e)) is not None][-8:]
        feed.markdown("".join(_step_html(s) for s in reversed(recent)), unsafe_allow_html=True)
        if finished:
            break
        time.sleep(REFRESH_S)
    feed.empty()


def _rerun_verdict(rerun: Rerun) -> None:
    if rerun.error:
        st.error(f"The re-run stopped: {rerun.error}")
    elif rerun.matches_recording():
        st.success("The re-run reached exactly the recorded report.")
    else:
        st.info(
            f"The re-run differs from the recording ({rerun.divergences} requests did not match "
            "exactly). Recorded replies come back faster than they did live, so agents can "
            "finish in another order, or a slow step no longer runs out of time, and some "
            "recorded replies no longer fit. The recorded run is the one that was scored."
        )


def _step_through(events: list[dict[str, object]], system: str) -> None:
    described = [(i, s) for i, e in enumerate(events) if (s := describe(e)) is not None]
    if not described:
        st.caption("This trace has no steps to show.")
        return
    position = st.slider("Step", 1, len(described), len(described), key=f"step-{len(events)}")
    upto = described[position - 1][0] + 1
    st.markdown(_lanes_html(agent_states(events[:upto]), system), unsafe_allow_html=True)
    current, board = st.columns([3, 2], gap="large")
    with current:
        st.markdown("##### This step")
        st.markdown(_step_html(described[position - 1][1]), unsafe_allow_html=True)
        st.markdown("##### Before it")
        earlier = [step for _, step in described[max(0, position - 9) : position - 1]]
        st.markdown("".join(_step_html(s) for s in reversed(earlier)), unsafe_allow_html=True)
    with board:
        _board_panel(board_at(events[:upto]))


def _board_panel(snapshot: BoardSnapshot) -> None:
    st.markdown("##### The shared board")
    with st.container(border=True):
        a, b, c = st.columns(3)
        a.metric("Round", snapshot.round or "-")
        b.metric("Observations", snapshot.observations)
        c.metric("Citations refused", snapshot.refused)
        if snapshot.standings:
            st.markdown("**Ranking at the end of the round**")
            st.markdown(_ranking_html(snapshot), unsafe_allow_html=True)
        if snapshot.verdicts or snapshot.objections:
            st.markdown("**Latest critic review**")
            chips = "".join(_verdict_chip(v.split(": ")[-1], v) for v in snapshot.verdicts)
            st.markdown(chips + style.bullet_list(snapshot.objections), unsafe_allow_html=True)
        if snapshot.requests:
            st.markdown("**Evidence the critic asked for**")
            st.markdown(style.bullet_list(snapshot.requests), unsafe_allow_html=True)


def _ranking_html(snapshot: BoardSnapshot) -> str:
    rows = []
    for standing in snapshot.standings:
        confidence = float(standing["confidence"])
        stated = float(standing["stated_confidence"])
        capped = f" (stated {stated:.0%})" if stated != confidence else ""
        verdict = standing.get("verdict")
        verdict_chip = _verdict_chip(str(verdict), str(verdict)) if verdict else ""
        rows.append(
            f'<div class="dense"><div><b>{escape(str(standing["hypothesis_id"]))}</b> '
            f"{escape(cause(standing))} {verdict_chip}</div>"
            f"{style.meter(confidence, '#6aa5ff')}"
            f'<div class="dim">{confidence:.0%}{escape(capped)}</div></div>'
        )
    return "".join(rows)


def _lanes_html(states: dict[str, AgentState], system: str) -> str:
    agents = ["solo"] if system == System.SINGLE else [a for a in AGENTS if a != "solo"]
    cells = []
    for agent in agents:
        state = states[agent]
        colour = style.AGENT_COLOURS[agent]
        working = " working" if state.status == "working" else ""
        cells.append(
            f'<div class="lane{working}" style="--lane-colour:{colour}">'
            f'<div class="name" style="color:{colour}">{agent}</div>'
            f'<div class="state">{style.chip(state.status, style.STATUS_KINDS[state.status])}</div>'
            f'<div class="counts">{state.tasks} tasks · {state.tool_calls} tool calls</div></div>'
        )
    return f'<div class="lanes">{"".join(cells)}</div>'


def _step_html(step: Step) -> str:
    failed = " failed" if step.failed else ""
    return (
        f'<div class="dense step{failed}">{style.agent_label(step.agent)}'
        f'<div><div class="what">{escape(step.text)}</div>'
        f"{style.bullet_list(step.details)}</div></div>"
    )


def _verdict_chip(verdict: str, label: str) -> str:
    return style.chip(label, style.VERDICT_KINDS.get(verdict, ""))


# --- Report ------------------------------------------------------------------------------


def _report_tab(report: Report) -> None:
    kind = "ok" if report.outcome is Outcome.CONCLUSIVE else "warn"
    st.markdown(
        style.chip(str(report.outcome), kind)
        + (style.chip(_cause_text(report), "info") if report.root_cause else "")
        + "".join(style.chip(r, "warn") for r in report.outcome_reasons),
        unsafe_allow_html=True,
    )
    st.markdown(report.summary)
    st.caption(f"Stopped because {report.termination}.")
    stats = report.stats
    a, b, c, d = st.columns(4)
    a.metric("Rounds", stats.rounds)
    b.metric("Model calls", stats.model_calls)
    c.metric("Tool calls", stats.tool_calls)
    d.metric("Tokens", f"{stats.tokens:,}")
    st.markdown("#### Hypotheses")
    if not report.hypotheses:
        st.caption("No hypothesis was established.")
    facts = {fact.id: fact for fact in report.facts}
    assumptions = {a.id: a for a in report.assumptions}
    for ranked in report.hypotheses:
        _hypothesis(ranked, facts, assumptions)
    left, right = st.columns(2)
    with left:
        st.markdown("#### Recommended actions")
        for action in report.actions:
            st.markdown(f"- **{action.urgency} · {action.kind}:** {action.description}")
        if report.open_questions:
            st.markdown("#### Open questions")
            st.markdown("\n".join(f"- {q}" for q in report.open_questions))
    with right:
        st.markdown("#### Evidence gaps")
        if report.gaps:
            st.table(
                [{"Source": g.tool, "Scope": g.scope, "Reason": g.reason} for g in report.gaps]
            )
        else:
            st.caption("None.")


def _hypothesis(
    ranked: RankedHypothesis,
    facts: Mapping[str, Observation],
    assumptions: Mapping[str, Assumption],
) -> None:
    hypothesis = ranked.hypothesis
    root = hypothesis.root_cause
    trigger = f", triggered by {root.trigger}" if root.trigger else ""
    title = (
        f"#{ranked.rank} {root.category} on {root.service}{trigger} · "
        f"{ranked.confidence:.0%} {ranked.confidence_band}"
        + (f" · critic: {ranked.verdict}" if ranked.verdict else "")
    )
    with st.expander(title, expanded=ranked.rank == 1):
        if ranked.calibration:
            st.caption(f"Capped from {hypothesis.confidence:.0%}: {'; '.join(ranked.calibration)}.")
        st.markdown(hypothesis.mechanism)
        supporting, contradicting = st.columns(2)
        supporting.markdown("**Supporting**")
        supporting.markdown(_facts_md(hypothesis.supporting, facts))
        contradicting.markdown("**Contradicting**")
        contradicting.markdown(_facts_md(hypothesis.contradicting, facts))
        if hypothesis.assumptions:
            st.markdown("**Relies on assumptions**")
            st.markdown(
                "\n".join(
                    f"- {assumptions[i].statement}"
                    for i in hypothesis.assumptions
                    if i in assumptions
                )
            )
        if ranked.objections:
            st.markdown("**Critic objections**")
            st.markdown(
                "\n".join(f"- [{o.severity}] {o.kind}: {o.detail}" for o in ranked.objections)
            )


def _facts_md(ids: tuple[str, ...], facts: Mapping[str, Observation]) -> str:
    lines = [
        f"- {facts[i].statement} " + " ".join(f"`{a}`" for a in facts[i].artifacts)
        for i in ids
        if i in facts
    ]
    return "\n".join(lines) or "_None._"


def _cause_text(report: Report) -> str:
    root = report.root_cause
    if root is None:
        return ""
    trigger = f" ({root.trigger})" if root.trigger else ""
    return f"{root.category} on {root.service}{trigger}"


# --- Comparison and scoreboard -----------------------------------------------------------


def _compare_tab(results: SweepResults, run: RecordedRun) -> None:
    incident = run.record.incident_id
    scores = sorted(
        (s for s in results.scores if s.incident_id == incident),
        key=lambda s: (s.system, s.trial),
    )
    if not scores:
        st.caption("No scored runs for this incident yet.")
        return
    st.markdown(f"Every recorded run of **{incident}**, scored against its ground truth.")
    st.table([_comparison_row(s) for s in scores])


def _comparison_row(score: RunScore) -> dict[str, object]:
    return {
        "System": SYSTEM_NAMES[System(score.system)],
        "Trial": score.trial,
        "Outcome": str(score.outcome),
        "Right": "yes" if score.correct else "no",
        "Top confidence": f"{score.top_confidence:.0%}"
        if score.top_confidence is not None
        else "-",
        "Model calls": score.model_calls,
        "Tool calls": score.tool_calls,
        "Tokens": f"{score.tokens:,}",
        "Wall clock": f"{score.wall_s / 60:.1f} min",
    }


def _scoreboard(results: SweepResults) -> None:
    if not results.scores:
        st.caption("No scored runs yet.")
        return
    names = [SYSTEM_NAMES[s] for s in results.systems]
    rows = [
        {"": label, **dict(zip(names, cells, strict=True))}
        for label, cells in overall_rows(results)
    ]
    st.table(rows)
    st.markdown("#### By incident")
    grid = []
    for incident in sorted({s.incident_id for s in results.scores}):
        row: dict[str, object] = {"Incident": incident}
        for system, name in zip(results.systems, names, strict=True):
            runs = [s for s in results.of(system) if s.incident_id == incident]
            row[name] = f"{sum(s.correct for s in runs)}/{len(runs)} right"
        grid.append(row)
    st.table(grid)


main()
