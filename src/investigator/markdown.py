"""Render a report as Markdown, resolving every citation to the fact and artifacts behind it."""

from collections.abc import Iterable, Mapping

from investigator.domain.causes import Outcome, RootCause
from investigator.domain.investigation import Assumption, Observation
from investigator.domain.report import RankedHypothesis, Report


def render_markdown(report: Report) -> str:
    facts = {o.id: o for o in report.facts}
    assumptions = {a.id: a for a in report.assumptions}
    lines = [f"# {report.incident_id}: {report.title}", ""]

    if report.outcome is Outcome.CONCLUSIVE and report.root_cause is not None:
        lines.append(f"**Outcome:** conclusive. Root cause: {_cause(report.root_cause)}")
    else:
        lines.append("**Outcome:** inconclusive")
        lines += [f"- {reason}" for reason in report.outcome_reasons]
    lines += ["", "## Summary", "", report.summary, "", "## Hypotheses", ""]

    for ranked in report.hypotheses:
        lines += _hypothesis(ranked, facts, assumptions)
    if not report.hypotheses:
        lines += ["No hypothesis was established.", ""]

    if report.actions:
        lines += [
            "## Recommended actions",
            "",
            "| Urgency | Kind | Action | Why |",
            "|---|---|---|---|",
        ]
        lines += [
            f"| {a.urgency} | {a.kind} | {a.description} | {a.rationale}"
            f"{f' ({a.hypothesis_id})' if a.hypothesis_id else ''} |"
            for a in report.actions
        ]
        lines.append("")
    if report.gaps:
        lines += ["## Evidence gaps", ""]
        lines += [f"- **{g.tool}** ({g.scope}): {g.reason}" for g in report.gaps]
        lines.append("")
    if report.open_questions:
        lines += ["## Open questions", ""]
        lines += [f"- {question}" for question in report.open_questions]
        lines.append("")

    stats = report.stats
    lines += [
        "## How the investigation ran",
        "",
        f"Stopped because {report.termination}, after {stats.rounds} round(s): "
        f"{stats.model_calls} model calls, {stats.tool_calls} tool calls, "
        f"{stats.tokens:,} tokens, {stats.elapsed_s:.0f} s.",
        "",
    ]
    return "\n".join(lines)


def _cause(cause: RootCause) -> str:
    trigger = f", triggered by `{cause.trigger}`" if cause.trigger else ""
    return f"`{cause.category}` on **{cause.service}**{trigger}"


def _hypothesis(
    ranked: RankedHypothesis,
    facts: Mapping[str, Observation],
    assumptions: Mapping[str, Assumption],
) -> list[str]:
    h = ranked.hypothesis
    verdict = f", critic: {ranked.verdict}" if ranked.verdict else ""
    lines = [
        f"### {ranked.rank}. {_cause(h.root_cause)} ({h.id})",
        "",
        f"Confidence {ranked.confidence:.2f} ({ranked.confidence_band}){verdict}"
        f"{_capped(ranked)}. {h.mechanism}",
        "",
    ]
    lines += _cited("Supporting", h.supporting, facts)
    lines += _cited("Contradicting", h.contradicting, facts)
    if h.assumptions:
        lines.append("**Assumptions:**")
        lines += [
            f"- {i}: {assumptions[i].statement if i in assumptions else i}" for i in h.assumptions
        ]
    if ranked.objections:
        lines.append("**Objections:**")
        lines += [f"- [{o.severity}] {o.kind}: {o.detail}" for o in ranked.objections]
    lines.append("")
    return lines


def _capped(ranked: RankedHypothesis) -> str:
    if not ranked.calibration:
        return ""
    return f", capped from {ranked.hypothesis.confidence:.2f}: {'; '.join(ranked.calibration)}"


def _cited(label: str, ids: Iterable[str], facts: Mapping[str, Observation]) -> list[str]:
    ids = list(ids)
    if not ids:
        return []
    lines = [f"**{label}:**"]
    for i in ids:
        fact = facts.get(i)
        if fact is None:
            lines.append(f"- {i}")
        else:
            lines.append(f"- {fact.statement} ({', '.join(f'`{a}`' for a in fact.artifacts)})")
    return lines
