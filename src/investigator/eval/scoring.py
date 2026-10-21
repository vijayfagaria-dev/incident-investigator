"""Scoring one run: was the answer right, was it grounded, and what did it cost.

Inputs are what a run leaves behind (its report, trace and run record), the ground truth
and the incident's telemetry, which resolves cited log ids to the lines they name.
"""

import re
from collections.abc import Iterable, Mapping
from typing import Any

from investigator.domain.base import DomainModel
from investigator.domain.causes import Outcome, RootCause
from investigator.domain.report import RankedHypothesis, Report
from investigator.domain.telemetry import LogRecord
from investigator.eval.ground_truth import GroundTruth, Tag
from investigator.eval.runner import RunRecord

ARTIFACT_PATTERN = re.compile(
    r"\b(?:chg:\d+|pir:\d{4}-\d{3}|dep:[a-z0-9-]+->[a-z0-9-]+|metric:[a-z0-9-]+/[a-z0-9_.]+"
    r"|log:[0-9a-f]{12}(?:-\d+)?)"
)
"""Artifact ids as they appear in free text such as a report's summary."""

_REFUSED = ("dropped observation citing nothing", "removed citations no tool returned")
"""How the board words a citation it refused."""


class RunScore(DomainModel):
    incident_id: str
    system: str
    trial: int
    tags: tuple[Tag, ...]
    expected: Outcome
    outcome: Outcome

    correct: bool
    """Concluded the true cause, or stayed inconclusive when the evidence could not tell."""
    top1: bool | None
    """The top hypothesis names the true cause, whatever the outcome. None if unanswerable."""
    top3: bool | None
    wrong_conclusion: bool
    """Concluded, and the conclusion is wrong."""
    confidently_wrong: bool
    """A wrong conclusion stated with high confidence."""
    abstained: bool
    """Inconclusive on an incident the evidence could answer."""
    top_confidence: float | None

    citations: int
    """Artifact ids the report cites, in its evidence and in its text."""
    valid_citations: int
    """Of those, ids a tool actually returned during the run."""
    rejected_citations: int
    """Citations agents made that the board refused because no tool returned them."""
    key_evidence: int
    key_evidence_cited: int
    """Ground-truth key evidence cited in support of a hypothesis naming the true cause."""
    red_herrings_cited: int
    """Planted decoys cited in support of the top hypothesis."""

    model_calls: int
    model_errors: int
    backup_model_calls: int
    """Requests the main model still failed after its retries, passed to the backup model."""
    prompt_tokens: int
    completion_tokens: int
    tool_calls: int
    tool_attempts: int
    tool_failures: int
    rounds: int
    wall_s: float
    llm_s: float
    rate_limit_wait_s: float

    @property
    def tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


def matches(cause: RootCause | None, truth: GroundTruth) -> bool:
    """Right service and category; the trigger is checked through key evidence instead."""
    if cause is None or truth.root_cause is None:
        return False
    accepted = (truth.root_cause, *truth.acceptable_alternates)
    return any((cause.service, cause.category) == (a.service, a.category) for a in accepted)


def score_run(
    record: RunRecord,
    report: Report,
    trace: Iterable[Mapping[str, Any]],
    truth: GroundTruth,
    logs: Mapping[str, LogRecord],
) -> RunScore:
    events = list(trace)
    model_calls = _events(events, "model_call")
    tool_calls = _events(events, "tool_call")

    # Was the answer right?
    answerable = truth.expected_outcome is Outcome.CONCLUSIVE
    concluded = report.outcome is Outcome.CONCLUSIVE
    ranked = report.hypotheses
    top = ranked[0] if ranked else None
    top1: bool | None = None
    top3: bool | None = None
    if answerable:
        correct = concluded and matches(report.root_cause, truth)
        top1 = top is not None and matches(top.hypothesis.root_cause, truth)
        top3 = any(matches(h.hypothesis.root_cause, truth) for h in ranked[:3])
    else:
        correct = not concluded
    wrong = concluded and not correct
    confident = top is not None and top.confidence_band == "high"

    # Was it grounded?
    returned = {artifact for e in tool_calls for artifact in e.get("artifacts", ())}
    cited = _cited_artifacts(report)
    refused = 0
    for commit in _events(events, "agent_commit"):
        refused += sum(problem.startswith(_REFUSED) for problem in commit.get("problems", ()))

    return RunScore(
        incident_id=record.incident_id,
        system=record.system,
        trial=record.trial,
        tags=truth.tags,
        expected=truth.expected_outcome,
        outcome=report.outcome,
        correct=correct,
        top1=top1,
        top3=top3,
        wrong_conclusion=wrong,
        confidently_wrong=wrong and confident,
        abstained=answerable and not concluded,
        top_confidence=top.confidence if top else None,
        citations=len(cited),
        valid_citations=len(cited & returned),
        rejected_citations=refused,
        key_evidence=_key_evidence_count(truth),
        key_evidence_cited=_key_evidence_cited(report, truth, logs) if answerable else 0,
        red_herrings_cited=len(set(truth.red_herrings) & _supporting_artifacts(report, top)),
        model_calls=len(model_calls),
        model_errors=sum(bool(e.get("error")) for e in model_calls),
        backup_model_calls=len(_events(events, "model_fallback")),
        prompt_tokens=sum(e.get("prompt_tokens") or 0 for e in model_calls),
        completion_tokens=sum(e.get("completion_tokens") or 0 for e in model_calls),
        tool_calls=len(tool_calls),
        tool_attempts=len(_events(events, "tool_attempt")),
        tool_failures=sum(e.get("status") == "error" for e in tool_calls),
        rounds=report.stats.rounds,
        wall_s=record.wall_s,
        llm_s=_seconds(model_calls, "latency_ms"),
        rate_limit_wait_s=_seconds(model_calls, "rate_limit_wait_ms"),
    )


def _events(events: Iterable[Mapping[str, Any]], kind: str) -> list[Mapping[str, Any]]:
    return [e for e in events if e.get("event") == kind]


def _seconds(events: Iterable[Mapping[str, Any]], field: str) -> float:
    return round(sum(e.get(field) or 0 for e in events) / 1000, 1)


def _cited_artifacts(report: Report) -> set[str]:
    text = " ".join(
        (
            report.summary,
            *(f"{a.description} {a.rationale}" for a in report.actions),
            *report.open_questions,
        )
    )
    in_evidence = {a for fact in report.facts for a in fact.artifacts}
    return in_evidence | set(ARTIFACT_PATTERN.findall(text))


def _supporting_artifacts(report: Report, ranked: RankedHypothesis | None) -> set[str]:
    if ranked is None:
        return set()
    facts = {fact.id: fact for fact in report.facts}
    return {
        artifact
        for observation_id in ranked.hypothesis.supporting
        if observation_id in facts
        for artifact in facts[observation_id].artifacts
    }


def _key_evidence_count(truth: GroundTruth) -> int:
    key = truth.key_evidence
    return len(key.changes) + len(key.metrics) + len(key.log_patterns)


def _key_evidence_cited(report: Report, truth: GroundTruth, logs: Mapping[str, LogRecord]) -> int:
    right = next((h for h in report.hypotheses if matches(h.hypothesis.root_cause, truth)), None)
    support = _supporting_artifacts(report, right)
    key = truth.key_evidence
    lines = [logs[a] for a in support if a in logs]
    return (
        sum(change in support for change in key.changes)
        + sum(metric in support for metric in key.metrics)
        + sum(
            any(line.service == p.service and p.contains in line.message for line in lines)
            for p in key.log_patterns
        )
    )
