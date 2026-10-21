"""When to stop investigating, and whether the evidence supports a conclusion.

These are rules, not prompts, so they behave the same on every run.
"""

from dataclasses import dataclass

from investigator.domain.causes import Outcome
from investigator.domain.investigation import (
    EvidenceRequest,
    Hypothesis,
    ObjectionSeverity,
    Verdict,
)
from investigator.runtime.blackboard import BoardView
from investigator.runtime.budget import Budget
from investigator.tracing import Standing

# A cause must show up in the telemetry: an explanation backed only by a change record and
# timing, or only by a past incident, is capped however sure the model sounds.
CAP_NO_RUNTIME_EVIDENCE = 0.6
CAP_ANALOGY_ONLY = 0.4
CAP_BLOCKED = 0.5
_RUNTIME_EVIDENCE = frozenset({"log", "metric"})


@dataclass(frozen=True)
class CappedHypothesis:
    hypothesis: Hypothesis
    confidence: float
    """The stated confidence, capped by what the evidence can bear."""
    cap_reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class OutcomeDecision:
    outcome: Outcome
    ranked: tuple[CappedHypothesis, ...]
    reasons: tuple[str, ...]

    @property
    def top(self) -> CappedHypothesis | None:
        return self.ranked[0] if self.ranked else None


def blocking_objections(view: BoardView, hypothesis_id: str) -> int:
    latest = view.latest_review
    if latest is None:
        return 0
    return sum(
        o.hypothesis_id == hypothesis_id and o.severity is ObjectionSeverity.BLOCKING
        for o in latest.objections
    )


def cap_confidence(hypothesis: Hypothesis, view: BoardView) -> CappedHypothesis:
    kinds = view.evidence_kinds(hypothesis)
    caps: list[tuple[float, str]] = []
    if kinds and kinds <= {"pir"}:
        caps.append((CAP_ANALOGY_ONLY, "supported only by past incidents"))
    elif not kinds & _RUNTIME_EVIDENCE:
        caps.append((CAP_NO_RUNTIME_EVIDENCE, "no log or metric evidence supports it"))
    if blocking_objections(view, hypothesis.id):
        caps.append((CAP_BLOCKED, "it has unresolved blocking objections"))
    confidence = hypothesis.confidence
    reasons = []
    for cap, why in caps:
        if cap < hypothesis.confidence:
            confidence = min(confidence, cap)
            reasons.append(why)
    return CappedHypothesis(hypothesis, confidence, tuple(reasons))


def rank_hypotheses(view: BoardView) -> list[CappedHypothesis]:
    """Most confident first, by capped confidence; ties go to fewer blocking objections."""
    capped = [cap_confidence(h, view) for h in view.hypotheses]
    return sorted(
        capped,
        key=lambda c: (-c.confidence, blocking_objections(view, c.hypothesis.id), c.hypothesis.id),
    )


def decide_outcome(view: BoardView, min_confidence: float, min_margin: float) -> OutcomeDecision:
    ranked = tuple(rank_hypotheses(view))
    if not ranked:
        return OutcomeDecision(Outcome.INCONCLUSIVE, ranked, ("no hypothesis was established",))
    top, leader = ranked[0], ranked[0].hypothesis
    reasons = []
    if top.confidence < min_confidence:
        reasons.append(
            f"the leading hypothesis has confidence {top.confidence:.2f}, below {min_confidence}"
        )
    rival = next((c for c in ranked[1:] if c.hypothesis.root_cause != leader.root_cause), None)
    if rival is not None and top.confidence - rival.confidence < min_margin:
        reasons.append(f"{leader.id} and {rival.hypothesis.id} are too close to tell apart")
    if not leader.supporting:
        reasons.append(f"{leader.id} cites no supporting observations")
    if blocking_objections(view, leader.id):
        reasons.append(f"{leader.id} has unresolved blocking objections")
    latest = view.latest_review
    if latest is not None and latest.verdicts.get(leader.id) is Verdict.REJECT:
        reasons.append(f"the critic rejected {leader.id}")
    outcome = Outcome.INCONCLUSIVE if reasons else Outcome.CONCLUSIVE
    return OutcomeDecision(outcome, ranked, tuple(reasons))


def stop_reason(
    view: BoardView, budget: Budget, new_observations: int, max_rounds: int
) -> str | None:
    """Why the investigation should stop after this round, or ``None`` to continue."""
    ranked = rank_hypotheses(view)
    leader = ranked[0].hypothesis if ranked else None
    latest = view.latest_review
    if (
        leader is not None
        and latest is not None
        and latest.round == view.round
        and latest.verdicts.get(leader.id) is Verdict.ACCEPT
        and not blocking_objections(view, leader.id)
    ):
        return f"the critic accepted {leader.id}"
    if reason := budget.exploration_stop_reason():
        return reason
    if view.round >= max_rounds:
        return f"reached the limit of {max_rounds} rounds"
    if view.round > 1 and new_observations == 0:
        return "the last round produced no new evidence"
    if not any(request.round == view.round for request in view.requests):
        return "no further evidence was requested"
    return None


def requests_to_pursue(view: BoardView, round_no: int) -> list[EvidenceRequest]:
    """This round's requests, minus those that only separate hypotheses the critic rejected."""
    latest = view.latest_review
    rejected = set()
    if latest is not None:
        rejected = {h for h, verdict in latest.verdicts.items() if verdict is Verdict.REJECT}
    wanted = []
    for request in view.requests:
        if request.round != round_no:
            continue
        only_about_rejected = bool(request.discriminates) and set(request.discriminates) <= rejected
        if not only_about_rejected:
            wanted.append(request)
    return wanted


def standings(view: BoardView) -> tuple[Standing, ...]:
    """The ranking as it stands, for the trace."""
    latest = view.latest_review
    if latest is not None and latest.round != view.round:
        latest = None
    return tuple(
        Standing(
            hypothesis_id=c.hypothesis.id,
            version=c.hypothesis.version,
            service=c.hypothesis.root_cause.service,
            category=c.hypothesis.root_cause.category,
            trigger=c.hypothesis.root_cause.trigger,
            stated_confidence=c.hypothesis.confidence,
            confidence=c.confidence,
            verdict=latest.verdicts.get(c.hypothesis.id) if latest else None,
            blocking_objections=blocking_objections(view, c.hypothesis.id),
        )
        for c in rank_hypotheses(view)
    )
