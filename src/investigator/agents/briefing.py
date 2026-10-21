"""Plain-text renderings of board content, shared by the agents' briefs."""

from collections.abc import Iterable
from datetime import datetime

from investigator.domain.incident import IncidentReport
from investigator.domain.investigation import (
    CriticReview,
    EvidenceGap,
    EvidenceRequest,
    Hypothesis,
    Lead,
    Observation,
)

NONE = "(none)"


def when(ts: datetime | None) -> str:
    return f"{ts:%Y-%m-%d %H:%M} UTC" if ts else "unspecified"


def incident(report: IncidentReport) -> str:
    lines = [
        f"INCIDENT {report.id}: {report.title} ({report.severity})",
        f"Reported {when(report.reported_at)} by {report.reported_by}.",
        f"Summary: {report.summary.strip()}",
        "Symptoms:",
        *(f"- {symptom}" for symptom in report.symptoms),
    ]
    if report.reported_services:
        lines.append(f"Reported services: {', '.join(report.reported_services)}")
    if report.responder_notes:
        lines += [
            "Responder notes (unverified):",
            *(f"- {note}" for note in report.responder_notes),
        ]
    return "\n".join(lines)


def observations(items: Iterable[Observation]) -> str:
    lines = [
        f"{o.id} [{o.source}]{f' {o.service}:' if o.service else ''} {o.statement} "
        f"(cites {', '.join(o.artifacts)})"
        for o in items
    ]
    return "\n".join(lines) or NONE


def hypotheses(items: Iterable[Hypothesis]) -> str:
    blocks = []
    for h in items:
        trigger = f", trigger {h.root_cause.trigger}" if h.root_cause.trigger else ""
        blocks.append(
            "\n".join(
                (
                    f"{h.id} v{h.version} (round {h.round}), confidence {h.confidence:.2f}: "
                    f"{h.root_cause.service} / {h.root_cause.category}{trigger}",
                    f"  mechanism: {h.mechanism}",
                    f"  supporting: {', '.join(h.supporting) or '-'}; "
                    f"contradicting: {', '.join(h.contradicting) or '-'}; "
                    f"assumptions: {', '.join(h.assumptions) or '-'}",
                    *(f"  prediction: {p}" for p in h.predictions),
                )
            )
        )
    return "\n".join(blocks) or NONE


def review(item: CriticReview | None) -> str:
    if item is None:
        return NONE
    lines = [f"Critic review of round {item.round}:"]
    lines += [f"- {hypothesis}: {verdict}" for hypothesis, verdict in item.verdicts.items()]
    lines += [
        f"- objection on {o.hypothesis_id} [{o.severity}, {o.kind}, from {o.source}]: {o.detail}"
        for o in item.objections
    ]
    return "\n".join(lines)


def requests(items: Iterable[EvidenceRequest]) -> str:
    lines = []
    for r in items:
        line = f"{r.id} [{r.domain}, from {r.requested_by}] {r.question}"
        if r.service:
            line += f" (service {r.service})"
        if r.start or r.end:
            line += f" {when(r.start)} to {when(r.end)}"
        if r.discriminates:
            line += f"; separates {', '.join(r.discriminates)}"
        lines.append(line)
    return "\n".join(lines) or NONE


def leads(items: Iterable[Lead]) -> str:
    lines = [f"{lead.id} [{lead.domain}, from {lead.source}] {lead.question}" for lead in items]
    return "\n".join(lines) or NONE


def gaps(items: Iterable[EvidenceGap]) -> str:
    return "\n".join(f"{g.id} {g.tool} ({g.scope}): {g.reason}" for g in items) or NONE
