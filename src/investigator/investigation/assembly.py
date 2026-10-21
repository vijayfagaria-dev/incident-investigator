"""Building the final report from the board, the policy's decision and the narrative."""

from investigator.agents.outputs import ReportNarrative
from investigator.domain.causes import Outcome
from investigator.domain.report import ConfidenceBand, RankedHypothesis, Report, RunStats
from investigator.investigation.policy import OutcomeDecision
from investigator.runtime.blackboard import BoardView

HIGH_CONFIDENCE, MEDIUM_CONFIDENCE = 0.75, 0.5


def fallback_narrative(decision: OutcomeDecision, termination: str) -> ReportNarrative:
    """Used when the reporting agent fails: plain statements, with no claims beyond the board."""
    top = decision.top
    if decision.outcome is Outcome.CONCLUSIVE and top is not None:
        cause = top.hypothesis.root_cause
        summary = (
            f"The most likely cause is {cause.category} on {cause.service} "
            f"({top.hypothesis.id}, confidence {top.confidence:.2f}). "
            "The narrative could not be generated; "
            "see the hypotheses and evidence below."
        )
    else:
        summary = (
            f"The investigation was inconclusive: {'; '.join(decision.reasons)}. "
            f"It stopped because {termination}."
        )
    return ReportNarrative(summary=summary)


def assemble(
    view: BoardView,
    decision: OutcomeDecision,
    narrative: ReportNarrative,
    termination: str,
    stats: RunStats,
) -> Report:
    latest = view.latest_review
    hypotheses = [c.hypothesis for c in decision.ranked]
    cited = {i for h in hypotheses for i in (*h.supporting, *h.contradicting)}
    used_assumptions = {i for h in hypotheses for i in h.assumptions}
    top = decision.top
    return Report(
        incident_id=view.incident.id,
        title=view.incident.title,
        outcome=decision.outcome,
        outcome_reasons=decision.reasons,
        summary=narrative.summary,
        root_cause=top.hypothesis.root_cause
        if decision.outcome is Outcome.CONCLUSIVE and top
        else None,
        hypotheses=tuple(
            RankedHypothesis(
                rank=rank,
                hypothesis=c.hypothesis,
                confidence=c.confidence,
                calibration=c.cap_reasons,
                confidence_band=_band(c.confidence),
                verdict=latest.verdicts.get(c.hypothesis.id) if latest else None,
                objections=tuple(o for o in latest.objections if o.hypothesis_id == c.hypothesis.id)
                if latest
                else (),
            )
            for rank, c in enumerate(decision.ranked, start=1)
        ),
        facts=tuple(o for o in view.observations if o.id in cited),
        assumptions=tuple(a for a in view.assumptions if a.id in used_assumptions),
        gaps=view.gaps,
        actions=narrative.actions,
        open_questions=narrative.open_questions,
        termination=termination,
        stats=stats,
    )


def _band(confidence: float) -> ConfidenceBand:
    if confidence >= HIGH_CONFIDENCE:
        return "high"
    return "medium" if confidence >= MEDIUM_CONFIDENCE else "low"
